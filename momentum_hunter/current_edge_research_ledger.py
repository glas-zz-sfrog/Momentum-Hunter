"""Offline immutable Current-Edge research evidence ledger.

The ledger records caller-supplied research evidence.  It does not observe a
production system, make a production decision, contact a provider or broker,
or expose order, update, or delete behavior.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


RESEARCH_ONLY = True
PRODUCTION_DECISION_AUTHORITY = "NONE"
EXECUTION_AUTHORITY = "NONE"

PREDICTION_SCHEMA = "argus-current-edge-frozen-prediction-packet-v1"
REVEAL_SCHEMA = "argus-current-edge-outcome-reveal-packet-v1"
RECEIPT_SCHEMA = "argus-current-edge-immutable-receipt-v1"
PREDICTION_PACKET_TYPE = "FROZEN_PREDICTION_PACKET"
REVEAL_PACKET_TYPE = "OUTCOME_REVEAL_PACKET"
LEDGER_DIRECTORY = "current-edge-research-ledger-v1"

MISSINGNESS_STATES = frozenset(
    {
        "OBSERVED",
        "MISSING",
        "UNAVAILABLE",
        "UNKNOWN",
        "NOT_APPLICABLE",
        "RECONSTRUCTED",
        "SYNTHETIC",
    }
)

_PREDICTION_COLLECTION = "predictions"
_PREDICTION_RECEIPT_COLLECTION = "prediction-receipts"
_REVEAL_COLLECTION = "reveals"
_REVEAL_RECEIPT_COLLECTION = "reveal-receipts"
_COLLECTIONS = frozenset(
    {
        _PREDICTION_COLLECTION,
        _PREDICTION_RECEIPT_COLLECTION,
        _REVEAL_COLLECTION,
        _REVEAL_RECEIPT_COLLECTION,
    }
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,254}$")
_PROHIBITED_PREDICTION_KEYS = frozenset(
    {
        "actual",
        "actual_value",
        "future_evidence",
        "label",
        "market_outcome",
        "outcome",
        "outcome_cutoff_at",
        "outcome_evidence",
        "outcome_resolved_at",
        "outcome_value",
        "realized",
        "realized_return",
        "resolution",
        "resolution_timestamp",
    }
)
_PROHIBITED_PREDICTION_VALUES = frozenset(
    {
        "FUTURE_EVIDENCE",
        "FUTURE_KNOWN",
        "OUTCOME_OBSERVED",
        "OUTCOME_RESOLVED",
        "REALIZED",
        "REALIZED_RETURN",
    }
)
_PROHIBITED_PREDICTION_VALUE_PATTERNS = (
    re.compile(r"(?:^|_)OUTCOME_(?:ACTUAL|KNOWN|OBSERVED|REALIZED|RESOLVED|VALUE|WAS)(?:_|$)"),
    re.compile(r"(?:^|_)(?:ACTUAL|REALIZED)_(?:LABEL|OUTCOME|PRICE|RESULT|RETURN|VALUE)(?:_|$)"),
    re.compile(r"(?:^|_)FUTURE_(?:EVIDENCE|KNOWN|OUTCOME|RESULT|VALUE)(?:_|$)"),
    re.compile(r"(?:^|_)(?:AFTER|POST)_CUTOFF_(?:EVIDENCE|OUTCOME|RESULT|VALUE)(?:_|$)"),
    re.compile(r"(?:^|_)KNOWN_AFTER_CUTOFF(?:_|$)"),
    re.compile(r"(?:^|_)(?:RESULT|RETURN|PNL|P_L)_(?:ACTUAL|FINAL|IS|KNOWN|OBSERVED|REALIZED|RESOLVED|WAS)(?:_|$)"),
    re.compile(r"(?:^|_)(?:ACTUAL|FINAL|REALIZED)_(?:LABEL|OUTCOME|P_L|PNL|PRICE|RESULT|RETURN|VALUE)(?:_|$)"),
    re.compile(r"(?:^|_)POST_EVENT_(?:OUTCOME|P_L|PNL|RESULT|RETURN|VALUE)(?:_|$)"),
    re.compile(r"(?:^|_)(?:FINAL|KNOWN|SETTLED)_(?:ANSWER|RESULT|VERDICT)(?:_|$)"),
    re.compile(r"(?:^|_)(?:ANSWER|VERDICT)_(?:FINAL|IS|KNOWN|RETURNED|SETTLED|WAS)(?:_|$)"),
    re.compile(r"(?:^|_)(?:LOST|WON)(?:_|$)"),
    re.compile(r"^(?:LOSS|P_L|PNL|PROFIT)$"),
    re.compile(r"(?:^|_)(?:LOSS|P_L|PNL|PROFIT)_(?:ACTUAL|FINAL|IS|KNOWN|OBSERVED|REALIZED|SETTLED|WAS)(?:_|$)"),
    re.compile(r"(?:^|_)(?:ACTUAL|FINAL|KNOWN|OBSERVED|REALIZED|SETTLED)_(?:LOSS|P_L|PNL|PROFIT)(?:_|$)"),
    re.compile(r"(?:^|_)RESULT_(?:LOSS|LOST|PROFIT|WON)(?:_|$)"),
)


class LedgerError(RuntimeError):
    """Visible deterministic fail-closed ledger error."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(f"{category}: {message}")


def _fail(category: str, message: str) -> None:
    raise LedgerError(category, message)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _fail("INVALID_VALUE", "JSON object keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _validate_json_value(value: Any, context: str) -> None:
    if value is None:
        _fail("INVALID_VALUE", f"{context} cannot use null as missingness")
    if isinstance(value, bool) or isinstance(value, str) or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("NONFINITE_NUMBER", f"{context} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("INVALID_VALUE", f"{context} contains a non-string object key")
            _validate_json_value(item, f"{context}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{context}[{index}]")
        return
    _fail("INVALID_VALUE", f"{context} contains unsupported value type")


def _canonical_json(value: Any, *, newline: bool = False) -> bytes:
    plain = _plain(value)
    _validate_json_value(plain, "canonical payload")
    try:
        encoded = json.dumps(
            plain,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LedgerError("INVALID_VALUE", "payload is not canonical JSON") from exc
    return encoded + (b"\n" if newline else b"")


def _domain_sha256(domain: str, value: Any) -> str:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\x00")
    digest.update(_canonical_json(value))
    return digest.hexdigest()


def _stored_bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stored_bytes_fingerprint(packet_type: str, value: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(f"{RECEIPT_SCHEMA}:stored-bytes-v1:{packet_type}".encode("ascii"))
    digest.update(b"\x00")
    digest.update(value)
    return digest.hexdigest()


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        _fail("UNKNOWN_FIELD", f"{context} has unknown fields: {', '.join(unknown)}")
    if missing:
        _fail("MISSING_FIELD", f"{context} is missing fields: {', '.join(missing)}")


def _require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail("INVALID_VALUE", f"{context} must be a nonblank exact string")
    if any(ord(character) < 32 for character in value):
        _fail("INVALID_VALUE", f"{context} contains control characters")
    return value


def _require_token(value: Any, context: str) -> str:
    text = _require_text(value, context)
    if not _TOKEN_RE.fullmatch(text) or ".." in text or "/" in text or "\\" in text:
        _fail("ROOT_PATH_INVALID", f"{context} is not an opaque path-safe identity token")
    return text


def _require_hash(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        _fail("INVALID_HASH", f"{context} must be a lowercase SHA-256 digest")
    return value


def _parse_utc(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        _fail("INVALID_TIMESTAMP", f"{context} must be an exact UTC RFC3339 Z instant")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LedgerError("INVALID_TIMESTAMP", f"{context} is not a calendar instant") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        _fail("INVALID_TIMESTAMP", f"{context} is not UTC")
    timespec = "microseconds" if "." in value else "seconds"
    if parsed.isoformat(timespec=timespec).replace("+00:00", "Z") != value:
        _fail("INVALID_TIMESTAMP", f"{context} is not losslessly normalized")
    return parsed


def _validate_owner_ref(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        _fail("INCOMPLETE_IDENTITY", f"{context} must be an owner-scoped reference")
    state = value.get("state")
    expected = {"owner_scope", "owner_identity", "fingerprint", "state"}
    if state == "SYNTHETIC":
        expected.add("fixture_identity")
    missing = sorted(expected - set(value))
    if missing:
        _fail("INCOMPLETE_IDENTITY", f"{context} is missing fields: {', '.join(missing)}")
    _require_exact_fields(value, expected, context)
    if state not in {"OBSERVED", "SYNTHETIC"}:
        _fail("INCOMPLETE_IDENTITY", f"{context} must be OBSERVED or SYNTHETIC")
    _require_token(value["owner_scope"], f"{context}.owner_scope")
    _require_token(value["owner_identity"], f"{context}.owner_identity")
    _require_hash(value["fingerprint"], f"{context}.fingerprint")
    if state == "SYNTHETIC":
        _require_token(value["fixture_identity"], f"{context}.fixture_identity")


def _validate_typed_ref(value: Any, context: str, *, event: bool = False) -> None:
    if not isinstance(value, Mapping):
        _fail("MISSINGNESS_INVALID", f"{context} must be a typed state")
    state = value.get("state")
    if state not in MISSINGNESS_STATES:
        _fail("MISSINGNESS_INVALID", f"{context} has an invalid missingness state")
    if state == "OBSERVED":
        expected = {"state", "value", "evidence_identity"}
    elif state == "SYNTHETIC":
        expected = {"state", "value", "fixture_identity"}
    elif state == "RECONSTRUCTED":
        expected = {
            "state",
            "value",
            "reconstruction_method",
            "source_inputs",
            "reconstructed_at",
            "non_recorded",
        }
    else:
        expected = {"state", "reason"}
    _require_exact_fields(value, expected, context)
    if state in {"MISSING", "UNAVAILABLE", "UNKNOWN", "NOT_APPLICABLE"}:
        _require_text(value["reason"], f"{context}.reason")
        return
    if state == "OBSERVED":
        _require_token(value["evidence_identity"], f"{context}.evidence_identity")
    elif state == "SYNTHETIC":
        _require_token(value["fixture_identity"], f"{context}.fixture_identity")
    else:
        _require_text(value["reconstruction_method"], f"{context}.reconstruction_method")
        if not isinstance(value["source_inputs"], (list, tuple)) or not value["source_inputs"]:
            _fail("MISSINGNESS_INVALID", f"{context}.source_inputs must be nonempty")
        for source in value["source_inputs"]:
            _require_token(source, f"{context}.source_inputs")
        _parse_utc(value["reconstructed_at"], f"{context}.reconstructed_at")
        if value["non_recorded"] is not True:
            _fail("MISSINGNESS_INVALID", f"{context}.non_recorded must be true")
    if not isinstance(value["value"], Mapping):
        _fail("MISSINGNESS_INVALID", f"{context}.value must be a typed identity object")
    expected_value = {"event_identity", "event_type"} if event else {"symbol", "entity_identity"}
    _require_exact_fields(value["value"], expected_value, f"{context}.value")
    for key in expected_value:
        _require_token(value["value"][key], f"{context}.value.{key}")


def _validate_source_evidence(value: Any, context: str) -> None:
    if not isinstance(value, Mapping):
        _fail("INVALID_EVIDENCE", f"{context} must be an evidence reference")
    state = value.get("state")
    expected = {
        "owner_scope",
        "evidence_id",
        "fingerprint",
        "available_at",
        "provenance_locator",
        "state",
    }
    if state == "SYNTHETIC":
        expected.add("fixture_identity")
    elif state == "RECONSTRUCTED":
        expected.update(
            {"reconstruction_method", "source_inputs", "reconstructed_at", "non_recorded"}
        )
    _require_exact_fields(value, expected, context)
    if state not in {"OBSERVED", "RECONSTRUCTED", "SYNTHETIC"}:
        _fail("INVALID_EVIDENCE", f"{context} must reference available immutable evidence")
    _require_token(value["owner_scope"], f"{context}.owner_scope")
    _require_token(value["evidence_id"], f"{context}.evidence_id")
    _require_hash(value["fingerprint"], f"{context}.fingerprint")
    _parse_utc(value["available_at"], f"{context}.available_at")
    _require_text(value["provenance_locator"], f"{context}.provenance_locator")
    if state == "SYNTHETIC":
        _require_token(value["fixture_identity"], f"{context}.fixture_identity")
    elif state == "RECONSTRUCTED":
        _require_text(value["reconstruction_method"], f"{context}.reconstruction_method")
        if not isinstance(value["source_inputs"], (list, tuple)) or not value["source_inputs"]:
            _fail("MISSINGNESS_INVALID", f"{context}.source_inputs must be nonempty")
        for source in value["source_inputs"]:
            _require_token(source, f"{context}.source_inputs")
        _parse_utc(value["reconstructed_at"], f"{context}.reconstructed_at")
        if value["non_recorded"] is not True:
            _fail("MISSINGNESS_INVALID", f"{context}.non_recorded must be true")


def _validate_bound_reconstruction_inputs(
    value: Mapping[str, Any], context: str, known_evidence_ids: set[str]
) -> None:
    if value.get("state") != "RECONSTRUCTED":
        return
    source_inputs = value["source_inputs"]
    if len(set(source_inputs)) != len(source_inputs):
        _fail("INVALID_EVIDENCE", f"{context}.source_inputs contains duplicates")
    if tuple(source_inputs) != tuple(sorted(source_inputs)):
        _fail("INVALID_EVIDENCE", f"{context}.source_inputs is not canonically ordered")
    unbound = sorted(set(source_inputs) - known_evidence_ids)
    if unbound:
        _fail(
            "INVALID_EVIDENCE",
            f"{context}.source_inputs references unbound evidence: {', '.join(unbound)}",
        )


def _validate_state_record(
    value: Any,
    context: str,
    *,
    identity_field: str,
    known_evidence_ids: set[str],
) -> None:
    if not isinstance(value, Mapping):
        _fail("MISSINGNESS_INVALID", f"{context} must be a typed state record")
    state = value.get("state")
    if state not in MISSINGNESS_STATES:
        _fail("MISSINGNESS_INVALID", f"{context} has an invalid missingness state")
    if state == "OBSERVED":
        expected = {identity_field, "state", "value", "evidence_ids"}
    elif state == "SYNTHETIC":
        expected = {identity_field, "state", "value", "evidence_ids", "fixture_identity"}
    elif state == "RECONSTRUCTED":
        expected = {
            identity_field,
            "state",
            "value",
            "evidence_ids",
            "reconstruction_method",
            "source_inputs",
            "reconstructed_at",
            "non_recorded",
        }
    else:
        expected = {identity_field, "state", "reason"}
    _require_exact_fields(value, expected, context)
    _require_token(value[identity_field], f"{context}.{identity_field}")
    if state in {"MISSING", "UNAVAILABLE", "UNKNOWN", "NOT_APPLICABLE"}:
        _require_text(value["reason"], f"{context}.reason")
        return
    _validate_json_value(value["value"], f"{context}.value")
    if isinstance(value["value"], Mapping):
        _fail("INVALID_VALUE", f"{context}.value cannot hide an untyped object")
    evidence_ids = value["evidence_ids"]
    if not isinstance(evidence_ids, (list, tuple)) or not evidence_ids:
        _fail("INVALID_EVIDENCE", f"{context}.evidence_ids must be nonempty")
    if len(set(evidence_ids)) != len(evidence_ids):
        _fail("DUPLICATE_EVIDENCE", f"{context}.evidence_ids contains duplicates")
    if tuple(evidence_ids) != tuple(sorted(evidence_ids)):
        _fail("NONCANONICAL_VALUE", f"{context}.evidence_ids are not canonically ordered")
    for evidence_id in evidence_ids:
        _require_token(evidence_id, f"{context}.evidence_ids")
        if evidence_id not in known_evidence_ids:
            _fail("INVALID_EVIDENCE", f"{context} references unknown evidence {evidence_id}")
    if state == "SYNTHETIC":
        _require_token(value["fixture_identity"], f"{context}.fixture_identity")
    elif state == "RECONSTRUCTED":
        _require_text(value["reconstruction_method"], f"{context}.reconstruction_method")
        if not isinstance(value["source_inputs"], (list, tuple)) or not value["source_inputs"]:
            _fail("MISSINGNESS_INVALID", f"{context}.source_inputs must be nonempty")
        for source in value["source_inputs"]:
            _require_token(source, f"{context}.source_inputs")
        _parse_utc(value["reconstructed_at"], f"{context}.reconstructed_at")
        if value["non_recorded"] is not True:
            _fail("MISSINGNESS_INVALID", f"{context}.non_recorded must be true")
        _validate_bound_reconstruction_inputs(value, context, known_evidence_ids)


def _validate_prediction_record(value: Any, context: str, evidence_ids: set[str]) -> None:
    if not isinstance(value, Mapping):
        _fail("INVALID_PREDICTION", f"{context} must be a typed prediction")
    expected = {
        "prediction_id",
        "prediction_object",
        "value",
        "horizon",
        "units",
        "rule_identity",
        "evidence_coverage",
    }
    _require_exact_fields(value, expected, context)
    _require_token(value["prediction_id"], f"{context}.prediction_id")
    _require_text(value["prediction_object"], f"{context}.prediction_object")
    _validate_json_value(value["value"], f"{context}.value")
    if isinstance(value["value"], Mapping):
        _fail("INVALID_VALUE", f"{context}.value cannot hide an untyped object")
    _require_text(value["horizon"], f"{context}.horizon")
    _require_text(value["units"], f"{context}.units")
    _validate_owner_ref(value["rule_identity"], f"{context}.rule_identity")
    coverage = value["evidence_coverage"]
    if not isinstance(coverage, (list, tuple)):
        _fail("INVALID_EVIDENCE", f"{context}.evidence_coverage must be an array")
    if len(set(coverage)) != len(coverage):
        _fail("DUPLICATE_EVIDENCE", f"{context}.evidence_coverage contains duplicates")
    if tuple(coverage) != tuple(sorted(coverage)):
        _fail("NONCANONICAL_VALUE", f"{context}.evidence_coverage is not canonically ordered")
    for evidence_id in coverage:
        _require_token(evidence_id, f"{context}.evidence_coverage")
        if evidence_id not in evidence_ids:
            _fail("INVALID_EVIDENCE", f"{context} references unknown evidence {evidence_id}")


def _validate_uncertainty(value: Any) -> None:
    if not isinstance(value, Mapping):
        _fail("MISSINGNESS_INVALID", "uncertainty must be typed")
    if value.get("state") == "NOT_SUPPLIED":
        _require_exact_fields(value, {"state", "reason"}, "uncertainty")
        _require_text(value["reason"], "uncertainty.reason")
        return
    _require_exact_fields(value, {"state", "measures"}, "uncertainty")
    if value["state"] != "SUPPLIED" or not isinstance(value["measures"], (list, tuple)):
        _fail("MISSINGNESS_INVALID", "uncertainty must be SUPPLIED or NOT_SUPPLIED")
    if not value["measures"]:
        _fail("MISSINGNESS_INVALID", "SUPPLIED uncertainty cannot be empty")
    names: set[str] = set()
    for index, measure in enumerate(value["measures"]):
        if not isinstance(measure, Mapping):
            _fail("MISSINGNESS_INVALID", "uncertainty measure must be an object")
        _require_exact_fields(measure, {"measure", "value", "units"}, f"uncertainty[{index}]")
        name = _require_token(measure["measure"], f"uncertainty[{index}].measure")
        if name in names:
            _fail("MISSINGNESS_INVALID", "uncertainty measure is duplicated")
        names.add(name)
        _validate_json_value(measure["value"], f"uncertainty[{index}].value")
        _require_text(measure["units"], f"uncertainty[{index}].units")
    if tuple(measure["measure"] for measure in value["measures"]) != tuple(sorted(names)):
        _fail("NONCANONICAL_VALUE", "uncertainty measures are not canonically ordered")


def _validate_abstention(value: Any) -> None:
    if not isinstance(value, Mapping):
        _fail("INVALID_PREDICTION", "abstention_rejection_state must be typed")
    _require_exact_fields(value, {"state", "reasons"}, "abstention_rejection_state")
    if value["state"] not in {"PREDICTED", "ABSTAINED", "REJECTED", "WATCH"}:
        _fail("INVALID_PREDICTION", "abstention/rejection state is invalid")
    reasons = value["reasons"]
    if not isinstance(reasons, (list, tuple)) or not reasons:
        _fail("INVALID_PREDICTION", "abstention/rejection reasons must be nonempty")
    for reason in reasons:
        _require_text(reason, "abstention_rejection_state.reasons")


def _scan_prohibited_prediction_content(value: Any, context: str = "prediction") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key).strip())
            normalized = re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")
            tokens = set(normalized.split("_"))
            prohibited_key = (
                normalized in _PROHIBITED_PREDICTION_KEYS
                or bool(tokens & {"actual", "outcome", "realized", "resolution"})
                or ("future" in tokens and bool(tokens & {"evidence", "known", "outcome", "result", "value"}))
                or ({"post", "cutoff"} <= tokens)
                or ({"after", "cutoff"} <= tokens)
            )
            if prohibited_key:
                _fail(
                    "PROHIBITED_PREDICTION_CONTENT",
                    f"{context} contains prohibited outcome/future field {key}",
                )
            _scan_prohibited_prediction_content(item, f"{context}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_prohibited_prediction_content(item, f"{context}[{index}]")
    elif isinstance(value, str):
        normalized = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
        if normalized in _PROHIBITED_PREDICTION_VALUES or any(
            pattern.search(normalized) for pattern in _PROHIBITED_PREDICTION_VALUE_PATTERNS
        ):
            _fail(
                "PROHIBITED_PREDICTION_CONTENT",
                f"{context} contains prohibited outcome/future value",
            )


@dataclass(frozen=True)
class FrozenPredictionPacketV1:
    packet_schema_version: str
    packet_type: str
    research_only: bool
    production_decision_authority: str
    execution_authority: str
    research_protocol_id: Mapping[str, Any]
    research_opportunity_id: Mapping[str, Any]
    symbol_entity_ref: Mapping[str, Any]
    event_ref: Mapping[str, Any]
    prediction_cutoff_at: str
    evidence_availability_cutoff_at: str
    source_evidence_refs: tuple[Mapping[str, Any], ...]
    code_identity: Mapping[str, Any]
    strategy_identity: Mapping[str, Any]
    configuration_identity: Mapping[str, Any]
    runtime_identity: Mapping[str, Any]
    feature_observations: tuple[Mapping[str, Any], ...]
    research_predictions: tuple[Mapping[str, Any], ...]
    uncertainty: Mapping[str, Any]
    abstention_rejection_state: Mapping[str, Any]
    missingness_ledger: tuple[Mapping[str, Any], ...]
    outcome_state: str
    created_at: str
    canonical_fingerprint: str
    immutable_receipt_id: str

    def __post_init__(self) -> None:
        for name in (
            "research_protocol_id",
            "research_opportunity_id",
            "symbol_entity_ref",
            "event_ref",
            "source_evidence_refs",
            "code_identity",
            "strategy_identity",
            "configuration_identity",
            "runtime_identity",
            "feature_observations",
            "research_predictions",
            "uncertainty",
            "abstention_rejection_state",
            "missingness_ledger",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class OutcomeRevealPacketV1:
    reveal_schema_version: str
    packet_type: str
    research_only: bool
    production_decision_authority: str
    execution_authority: str
    original_prediction_fingerprint: str
    original_prediction_receipt_id: str
    research_protocol_id: Mapping[str, Any]
    research_opportunity_id: Mapping[str, Any]
    outcome_cutoff_at: str
    outcome_resolved_at: str
    outcome_evidence: tuple[Mapping[str, Any], ...]
    outcome_provenance: Mapping[str, Any]
    outcome_semantic_id: Mapping[str, Any]
    outcome_semantic_version: str
    outcome_values: tuple[Mapping[str, Any], ...]
    created_at: str
    canonical_fingerprint: str
    immutable_receipt_id: str

    def __post_init__(self) -> None:
        for name in (
            "research_protocol_id",
            "research_opportunity_id",
            "outcome_evidence",
            "outcome_provenance",
            "outcome_semantic_id",
            "outcome_values",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class ImmutableReceiptV1:
    receipt_schema_version: str
    record_type: str
    packet_type: str
    logical_key_digest: str
    canonical_fingerprint: str
    immutable_receipt_id: str
    packet_relative_path: str
    stored_bytes_sha256: str
    stored_bytes_fingerprint: str
    terminal_write_result: str


@dataclass(frozen=True)
class StoredArtifact:
    packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1
    receipt: ImmutableReceiptV1
    packet_path: Path
    receipt_path: Path
    created: bool
    idempotent: bool


def _prediction_semantic(packet: FrozenPredictionPacketV1) -> dict[str, Any]:
    value = _plain(packet)
    value.pop("canonical_fingerprint")
    value.pop("immutable_receipt_id")
    return value


def _reveal_semantic(packet: OutcomeRevealPacketV1) -> dict[str, Any]:
    value = _plain(packet)
    value.pop("canonical_fingerprint")
    value.pop("immutable_receipt_id")
    return value


def prediction_logical_key_digest(packet: FrozenPredictionPacketV1) -> str:
    return _domain_sha256(
        f"{PREDICTION_SCHEMA}:logical-key-v1",
        [
            packet.packet_schema_version,
            _plain(packet.research_protocol_id),
            _plain(packet.research_opportunity_id),
            packet.prediction_cutoff_at,
        ],
    )


def reveal_logical_key_digest(packet: OutcomeRevealPacketV1) -> str:
    return _domain_sha256(
        f"{REVEAL_SCHEMA}:logical-key-v1",
        [
            packet.reveal_schema_version,
            packet.original_prediction_fingerprint,
            _plain(packet.outcome_semantic_id),
            packet.outcome_semantic_version,
            packet.outcome_cutoff_at,
        ],
    )


def _packet_fingerprint(packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1) -> str:
    if isinstance(packet, FrozenPredictionPacketV1):
        return _domain_sha256(f"{PREDICTION_SCHEMA}:canonical-fingerprint-v1", _prediction_semantic(packet))
    return _domain_sha256(f"{REVEAL_SCHEMA}:canonical-fingerprint-v1", _reveal_semantic(packet))


def _receipt_id(
    packet_type: str,
    logical_key_digest: str,
    canonical_fingerprint: str,
) -> str:
    return _domain_sha256(
        f"{RECEIPT_SCHEMA}:identity-v1",
        [packet_type, logical_key_digest, canonical_fingerprint],
    )


def packet_bytes(packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1) -> bytes:
    return _canonical_json(packet, newline=True)


def _sorted_records(values: Sequence[Mapping[str, Any]], identity_field: str) -> tuple[Any, ...]:
    frozen = tuple(_freeze(value) for value in values)
    try:
        return tuple(sorted(frozen, key=lambda item: str(item[identity_field])))
    except (KeyError, TypeError) as exc:
        raise LedgerError("MISSING_FIELD", f"record is missing {identity_field}") from exc


def build_frozen_prediction_packet(
    *,
    research_protocol_id: Mapping[str, Any],
    research_opportunity_id: Mapping[str, Any],
    symbol_entity_ref: Mapping[str, Any],
    event_ref: Mapping[str, Any],
    prediction_cutoff_at: str,
    evidence_availability_cutoff_at: str,
    source_evidence_refs: Sequence[Mapping[str, Any]],
    code_identity: Mapping[str, Any],
    strategy_identity: Mapping[str, Any],
    configuration_identity: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    feature_observations: Sequence[Mapping[str, Any]],
    research_predictions: Sequence[Mapping[str, Any]],
    uncertainty: Mapping[str, Any],
    abstention_rejection_state: Mapping[str, Any],
    missingness_ledger: Sequence[Mapping[str, Any]],
    outcome_state: str,
    created_at: str,
) -> FrozenPredictionPacketV1:
    packet = FrozenPredictionPacketV1(
        packet_schema_version=PREDICTION_SCHEMA,
        packet_type=PREDICTION_PACKET_TYPE,
        research_only=RESEARCH_ONLY,
        production_decision_authority=PRODUCTION_DECISION_AUTHORITY,
        execution_authority=EXECUTION_AUTHORITY,
        research_protocol_id=research_protocol_id,
        research_opportunity_id=research_opportunity_id,
        symbol_entity_ref=symbol_entity_ref,
        event_ref=event_ref,
        prediction_cutoff_at=prediction_cutoff_at,
        evidence_availability_cutoff_at=evidence_availability_cutoff_at,
        source_evidence_refs=_sorted_records(source_evidence_refs, "evidence_id"),
        code_identity=code_identity,
        strategy_identity=strategy_identity,
        configuration_identity=configuration_identity,
        runtime_identity=runtime_identity,
        feature_observations=_sorted_records(feature_observations, "observation_id"),
        research_predictions=_sorted_records(research_predictions, "prediction_id"),
        uncertainty=uncertainty,
        abstention_rejection_state=abstention_rejection_state,
        missingness_ledger=_sorted_records(missingness_ledger, "field"),
        outcome_state=outcome_state,
        created_at=created_at,
        canonical_fingerprint="",
        immutable_receipt_id="",
    )
    fingerprint = _packet_fingerprint(packet)
    packet = replace(packet, canonical_fingerprint=fingerprint)
    packet = replace(
        packet,
        immutable_receipt_id=_receipt_id(
            packet.packet_type, prediction_logical_key_digest(packet), fingerprint
        ),
    )
    validate_frozen_prediction_packet(packet)
    return packet


def build_outcome_reveal_packet(
    *,
    original_prediction_fingerprint: str,
    original_prediction_receipt_id: str,
    research_protocol_id: Mapping[str, Any],
    research_opportunity_id: Mapping[str, Any],
    outcome_cutoff_at: str,
    outcome_resolved_at: str,
    outcome_evidence: Sequence[Mapping[str, Any]],
    outcome_provenance: Mapping[str, Any],
    outcome_semantic_id: Mapping[str, Any],
    outcome_semantic_version: str,
    outcome_values: Sequence[Mapping[str, Any]],
    created_at: str,
) -> OutcomeRevealPacketV1:
    packet = OutcomeRevealPacketV1(
        reveal_schema_version=REVEAL_SCHEMA,
        packet_type=REVEAL_PACKET_TYPE,
        research_only=RESEARCH_ONLY,
        production_decision_authority=PRODUCTION_DECISION_AUTHORITY,
        execution_authority=EXECUTION_AUTHORITY,
        original_prediction_fingerprint=original_prediction_fingerprint,
        original_prediction_receipt_id=original_prediction_receipt_id,
        research_protocol_id=research_protocol_id,
        research_opportunity_id=research_opportunity_id,
        outcome_cutoff_at=outcome_cutoff_at,
        outcome_resolved_at=outcome_resolved_at,
        outcome_evidence=_sorted_records(outcome_evidence, "evidence_id"),
        outcome_provenance=outcome_provenance,
        outcome_semantic_id=outcome_semantic_id,
        outcome_semantic_version=outcome_semantic_version,
        outcome_values=_sorted_records(outcome_values, "outcome_id"),
        created_at=created_at,
        canonical_fingerprint="",
        immutable_receipt_id="",
    )
    fingerprint = _packet_fingerprint(packet)
    packet = replace(packet, canonical_fingerprint=fingerprint)
    packet = replace(
        packet,
        immutable_receipt_id=_receipt_id(
            packet.packet_type, reveal_logical_key_digest(packet), fingerprint
        ),
    )
    validate_outcome_reveal_packet(packet)
    return packet


def validate_frozen_prediction_packet(packet: FrozenPredictionPacketV1) -> None:
    if not isinstance(packet, FrozenPredictionPacketV1):
        _fail("INVALID_SCHEMA", "prediction packet type is invalid")
    if packet.packet_schema_version != PREDICTION_SCHEMA or packet.packet_type != PREDICTION_PACKET_TYPE:
        _fail("INVALID_SCHEMA", "prediction schema or packet type is invalid")
    if (
        packet.research_only is not True
        or packet.production_decision_authority != PRODUCTION_DECISION_AUTHORITY
        or packet.execution_authority != EXECUTION_AUTHORITY
    ):
        _fail("INVALID_AUTHORITY", "prediction authority markers are invalid")
    prohibited_view = _prediction_semantic(packet)
    prohibited_view.pop("outcome_state")
    _scan_prohibited_prediction_content(prohibited_view)
    for name in (
        "research_protocol_id",
        "research_opportunity_id",
        "code_identity",
        "strategy_identity",
        "configuration_identity",
        "runtime_identity",
    ):
        _validate_owner_ref(getattr(packet, name), name)
    _validate_typed_ref(packet.symbol_entity_ref, "symbol_entity_ref")
    _validate_typed_ref(packet.event_ref, "event_ref", event=True)
    prediction_cutoff = _parse_utc(packet.prediction_cutoff_at, "prediction_cutoff_at")
    evidence_cutoff = _parse_utc(
        packet.evidence_availability_cutoff_at, "evidence_availability_cutoff_at"
    )
    _parse_utc(packet.created_at, "created_at")
    if evidence_cutoff > prediction_cutoff:
        _fail("INVALID_CHRONOLOGY", "evidence cutoff is after prediction cutoff")
    for field_name, typed_ref in (
        ("symbol_entity_ref", packet.symbol_entity_ref),
        ("event_ref", packet.event_ref),
    ):
        if typed_ref["state"] == "RECONSTRUCTED" and _parse_utc(
            typed_ref["reconstructed_at"], f"{field_name}.reconstructed_at"
        ) > evidence_cutoff:
            _fail("FUTURE_EVIDENCE", f"{field_name} reconstruction occurred after cutoff")
    evidence_ids: set[str] = set()
    for index, evidence in enumerate(packet.source_evidence_refs):
        _validate_source_evidence(evidence, f"source_evidence_refs[{index}]")
        evidence_id = evidence["evidence_id"]
        if evidence_id in evidence_ids:
            _fail("DUPLICATE_EVIDENCE", "source evidence identity is duplicated")
        evidence_ids.add(evidence_id)
        if _parse_utc(evidence["available_at"], f"source_evidence_refs[{index}].available_at") > evidence_cutoff:
            _fail("FUTURE_EVIDENCE", f"evidence {evidence_id} was unavailable at freeze")
        if evidence["state"] == "RECONSTRUCTED" and _parse_utc(
            evidence["reconstructed_at"], f"source_evidence_refs[{index}].reconstructed_at"
        ) > evidence_cutoff:
            _fail("FUTURE_EVIDENCE", f"reconstruction {evidence_id} occurred after cutoff")
    if tuple(item["evidence_id"] for item in packet.source_evidence_refs) != tuple(
        sorted(evidence_ids)
    ):
        _fail("NONCANONICAL_VALUE", "source_evidence_refs are not canonically ordered")
    _validate_bound_reconstruction_inputs(
        packet.symbol_entity_ref, "symbol_entity_ref", evidence_ids
    )
    _validate_bound_reconstruction_inputs(packet.event_ref, "event_ref", evidence_ids)
    observation_ids: set[str] = set()
    for index, observation in enumerate(packet.feature_observations):
        _validate_state_record(
            observation,
            f"feature_observations[{index}]",
            identity_field="observation_id",
            known_evidence_ids=evidence_ids,
        )
        identity = observation["observation_id"]
        if identity in observation_ids:
            _fail("DUPLICATE_IDENTITY", "feature observation identity is duplicated")
        observation_ids.add(identity)
        if observation["state"] == "RECONSTRUCTED" and _parse_utc(
            observation["reconstructed_at"], f"feature_observations[{index}].reconstructed_at"
        ) > evidence_cutoff:
            _fail("FUTURE_EVIDENCE", f"feature reconstruction {identity} occurred after cutoff")
    if tuple(item["observation_id"] for item in packet.feature_observations) != tuple(
        sorted(observation_ids)
    ):
        _fail("NONCANONICAL_VALUE", "feature_observations are not canonically ordered")
    prediction_ids: set[str] = set()
    for index, prediction in enumerate(packet.research_predictions):
        _validate_prediction_record(prediction, f"research_predictions[{index}]", evidence_ids)
        identity = prediction["prediction_id"]
        if identity in prediction_ids:
            _fail("DUPLICATE_IDENTITY", "research prediction identity is duplicated")
        prediction_ids.add(identity)
    if tuple(item["prediction_id"] for item in packet.research_predictions) != tuple(
        sorted(prediction_ids)
    ):
        _fail("NONCANONICAL_VALUE", "research_predictions are not canonically ordered")
    _validate_uncertainty(packet.uncertainty)
    _validate_abstention(packet.abstention_rejection_state)
    missing_fields: set[str] = set()
    for index, entry in enumerate(packet.missingness_ledger):
        _validate_state_record(
            entry,
            f"missingness_ledger[{index}]",
            identity_field="field",
            known_evidence_ids=evidence_ids,
        )
        field = entry["field"]
        if field in missing_fields:
            _fail("DUPLICATE_IDENTITY", "missingness field is duplicated")
        missing_fields.add(field)
        if entry["state"] == "RECONSTRUCTED" and _parse_utc(
            entry["reconstructed_at"], f"missingness_ledger[{index}].reconstructed_at"
        ) > evidence_cutoff:
            _fail("FUTURE_EVIDENCE", f"missingness reconstruction {field} occurred after cutoff")
    if tuple(item["field"] for item in packet.missingness_ledger) != tuple(sorted(missing_fields)):
        _fail("NONCANONICAL_VALUE", "missingness_ledger is not canonically ordered")
    if not packet.source_evidence_refs and "source_evidence_refs" not in missing_fields:
        _fail("MISSINGNESS_INVALID", "empty source evidence requires explicit missingness")
    if packet.outcome_state != "UNRESOLVED":
        _fail("PROHIBITED_PREDICTION_CONTENT", "prediction outcome_state must be UNRESOLVED")
    _require_hash(packet.canonical_fingerprint, "canonical_fingerprint")
    expected_fingerprint = _packet_fingerprint(packet)
    if packet.canonical_fingerprint != expected_fingerprint:
        _fail("FINGERPRINT_MISMATCH", "prediction canonical fingerprint does not match")
    expected_receipt = _receipt_id(
        packet.packet_type, prediction_logical_key_digest(packet), expected_fingerprint
    )
    if packet.immutable_receipt_id != expected_receipt:
        _fail("RECEIPT_MISMATCH", "prediction immutable receipt identity does not match")


def validate_outcome_reveal_packet(packet: OutcomeRevealPacketV1) -> None:
    if not isinstance(packet, OutcomeRevealPacketV1):
        _fail("INVALID_SCHEMA", "reveal packet type is invalid")
    if packet.reveal_schema_version != REVEAL_SCHEMA or packet.packet_type != REVEAL_PACKET_TYPE:
        _fail("INVALID_SCHEMA", "reveal schema or packet type is invalid")
    if (
        packet.research_only is not True
        or packet.production_decision_authority != PRODUCTION_DECISION_AUTHORITY
        or packet.execution_authority != EXECUTION_AUTHORITY
    ):
        _fail("INVALID_AUTHORITY", "reveal authority markers are invalid")
    _require_hash(packet.original_prediction_fingerprint, "original_prediction_fingerprint")
    _require_hash(packet.original_prediction_receipt_id, "original_prediction_receipt_id")
    _validate_owner_ref(packet.research_protocol_id, "research_protocol_id")
    _validate_owner_ref(packet.research_opportunity_id, "research_opportunity_id")
    cutoff = _parse_utc(packet.outcome_cutoff_at, "outcome_cutoff_at")
    resolved = _parse_utc(packet.outcome_resolved_at, "outcome_resolved_at")
    _parse_utc(packet.created_at, "created_at")
    if resolved > cutoff:
        _fail("INVALID_CHRONOLOGY", "outcome resolves after the outcome cutoff")
    evidence_ids: set[str] = set()
    for index, evidence in enumerate(packet.outcome_evidence):
        _validate_source_evidence(evidence, f"outcome_evidence[{index}]")
        identity = evidence["evidence_id"]
        if identity in evidence_ids:
            _fail("DUPLICATE_EVIDENCE", "outcome evidence identity is duplicated")
        evidence_ids.add(identity)
        if _parse_utc(evidence["available_at"], f"outcome_evidence[{index}].available_at") > cutoff:
            _fail("INVALID_CHRONOLOGY", f"outcome evidence {identity} is after outcome cutoff")
        if evidence["state"] == "RECONSTRUCTED" and _parse_utc(
            evidence["reconstructed_at"], f"outcome_evidence[{index}].reconstructed_at"
        ) > cutoff:
            _fail("INVALID_CHRONOLOGY", f"outcome reconstruction {identity} is after outcome cutoff")
    if tuple(item["evidence_id"] for item in packet.outcome_evidence) != tuple(sorted(evidence_ids)):
        _fail("NONCANONICAL_VALUE", "outcome_evidence is not canonically ordered")
    if not isinstance(packet.outcome_provenance, Mapping):
        _fail("INVALID_EVIDENCE", "outcome_provenance must be an object")
    _require_exact_fields(
        packet.outcome_provenance,
        {"source_identity", "retrieved_at", "transformation_identity", "admissibility_state"},
        "outcome_provenance",
    )
    _validate_owner_ref(packet.outcome_provenance["source_identity"], "outcome_provenance.source_identity")
    _validate_owner_ref(
        packet.outcome_provenance["transformation_identity"],
        "outcome_provenance.transformation_identity",
    )
    retrieved = _parse_utc(packet.outcome_provenance["retrieved_at"], "outcome_provenance.retrieved_at")
    if retrieved > cutoff:
        _fail("INVALID_CHRONOLOGY", "outcome provenance retrieval is after outcome cutoff")
    if packet.outcome_evidence and retrieved < max(
        _parse_utc(evidence["available_at"], "outcome_evidence.available_at")
        for evidence in packet.outcome_evidence
    ):
        _fail("INVALID_CHRONOLOGY", "outcome provenance retrieval precedes evidence availability")
    if packet.outcome_provenance["admissibility_state"] != "ADMITTED":
        _fail("INVALID_EVIDENCE", "outcome provenance is not admitted")
    _validate_owner_ref(packet.outcome_semantic_id, "outcome_semantic_id")
    _require_token(packet.outcome_semantic_version, "outcome_semantic_version")
    outcome_ids: set[str] = set()
    for index, outcome in enumerate(packet.outcome_values):
        _validate_state_record(
            outcome,
            f"outcome_values[{index}]",
            identity_field="outcome_id",
            known_evidence_ids=evidence_ids,
        )
        identity = outcome["outcome_id"]
        if identity in outcome_ids:
            _fail("DUPLICATE_IDENTITY", "outcome value identity is duplicated")
        outcome_ids.add(identity)
    if tuple(item["outcome_id"] for item in packet.outcome_values) != tuple(sorted(outcome_ids)):
        _fail("NONCANONICAL_VALUE", "outcome_values are not canonically ordered")
    if not packet.outcome_values:
        _fail("MISSINGNESS_INVALID", "outcome_values must explicitly resolve or censor the outcome")
    _require_hash(packet.canonical_fingerprint, "canonical_fingerprint")
    expected_fingerprint = _packet_fingerprint(packet)
    if packet.canonical_fingerprint != expected_fingerprint:
        _fail("FINGERPRINT_MISMATCH", "reveal canonical fingerprint does not match")
    expected_receipt = _receipt_id(
        packet.packet_type, reveal_logical_key_digest(packet), expected_fingerprint
    )
    if packet.immutable_receipt_id != expected_receipt:
        _fail("RECEIPT_MISMATCH", "reveal immutable receipt identity does not match")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(data: bytes, context: str) -> Mapping[str, Any]:
    try:
        text = data.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_strict_object, parse_constant=lambda item: _fail("NONFINITE_NUMBER", item))
    except LedgerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError("MALFORMED_JSON", f"{context} is not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        _fail("INVALID_SCHEMA", f"{context} must be a JSON object")
    return value


def _packet_from_mapping(
    record_type: type[FrozenPredictionPacketV1] | type[OutcomeRevealPacketV1],
    value: Mapping[str, Any],
) -> FrozenPredictionPacketV1 | OutcomeRevealPacketV1:
    expected = {field.name for field in fields(record_type)}
    _require_exact_fields(value, expected, record_type.__name__)
    try:
        packet = record_type(**value)
    except TypeError as exc:
        raise LedgerError("INVALID_SCHEMA", f"cannot construct {record_type.__name__}") from exc
    if isinstance(packet, FrozenPredictionPacketV1):
        validate_frozen_prediction_packet(packet)
    else:
        validate_outcome_reveal_packet(packet)
    return packet


def parse_prediction_json(data: bytes) -> FrozenPredictionPacketV1:
    packet = _packet_from_mapping(FrozenPredictionPacketV1, _strict_json(data, "prediction packet"))
    if not isinstance(packet, FrozenPredictionPacketV1):
        _fail("INVALID_SCHEMA", "parsed prediction has the wrong packet type")
    return packet


def parse_reveal_json(data: bytes) -> OutcomeRevealPacketV1:
    packet = _packet_from_mapping(OutcomeRevealPacketV1, _strict_json(data, "reveal packet"))
    if not isinstance(packet, OutcomeRevealPacketV1):
        _fail("INVALID_SCHEMA", "parsed reveal has the wrong packet type")
    return packet


def _receipt_from_json(data: bytes) -> ImmutableReceiptV1:
    value = _strict_json(data, "immutable receipt")
    expected = {field.name for field in fields(ImmutableReceiptV1)}
    _require_exact_fields(value, expected, "ImmutableReceiptV1")
    try:
        return ImmutableReceiptV1(**value)
    except TypeError as exc:
        raise LedgerError("INVALID_SCHEMA", "cannot construct immutable receipt") from exc


def _is_reparse(path: Path) -> bool:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(status, "st_file_attributes", 0)
    reparse_flag = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _assert_existing_prefixes_are_plain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() and _is_reparse(current):
            _fail("ROOT_REPARSE_POINT", f"storage path contains a link/reparse point: {current}")


def _assert_single_link(path: Path, context: str) -> None:
    try:
        link_count = path.stat(follow_symlinks=False).st_nlink
    except OSError as exc:
        raise LedgerError("STORAGE_IO", f"cannot inspect link count for {context}") from exc
    if link_count != 1:
        _fail(
            "ARTIFACT_LINK_COUNT_INVALID",
            f"{context} must have exactly one filesystem link; observed {link_count}",
        )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class CurrentEdgeResearchLedger:
    """Caller-rooted, filesystem-only, immutable prediction/reveal store."""

    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root)
        if not raw_root.is_absolute():
            _fail("ROOT_NOT_ABSOLUTE", "ledger root must be caller-supplied and absolute")
        if ".." in raw_root.parts:
            _fail("ROOT_PATH_INVALID", "ledger root cannot contain traversal components")
        _assert_existing_prefixes_are_plain(raw_root)
        try:
            raw_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LedgerError("STORAGE_IO", "cannot create caller root") from exc
        _assert_existing_prefixes_are_plain(raw_root)
        self.caller_root = raw_root.resolve(strict=True)
        self.root = self.caller_root / LEDGER_DIRECTORY
        if self.root.exists() and _is_reparse(self.root):
            _fail("ROOT_REPARSE_POINT", "ledger directory cannot be a link/reparse point")
        if self.root.exists():
            if not self.root.is_dir():
                _fail("ROOT_LAYOUT_INVALID", "ledger path is not a directory")
            self._validate_layout()
        else:
            self.root.mkdir(exist_ok=False)
            for collection in sorted(_COLLECTIONS):
                (self.root / collection).mkdir(exist_ok=False)
            self._validate_layout()
        self._predictions: dict[str, StoredArtifact] = {}
        self._reveals: dict[str, StoredArtifact] = {}
        self._reload()

    def _ensure_contained(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise LedgerError("ROOT_ESCAPE", "derived path is outside ledger root") from exc
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.root.resolve(strict=True))
        except ValueError as exc:
            raise LedgerError("ROOT_ESCAPE", "resolved path escapes ledger root") from exc
        _assert_existing_prefixes_are_plain(path)

    def _artifact_path(self, collection: str, digest: str) -> Path:
        if collection not in _COLLECTIONS:
            _fail("ROOT_PATH_INVALID", "unknown ledger collection")
        _require_hash(digest, "logical_key_digest")
        path = self.root / collection / digest[:2] / f"{digest}.json"
        self._ensure_contained(path)
        return path

    def _validate_layout(self) -> None:
        if _is_reparse(self.root):
            _fail("ROOT_REPARSE_POINT", "ledger root is a link/reparse point")
        observed_collections: set[str] = set()
        for entry in self.root.iterdir():
            if _is_reparse(entry):
                _fail("ROOT_REPARSE_POINT", f"ledger contains link/reparse point: {entry.name}")
            if entry.name.endswith(".tmp"):
                _fail("PARTIAL_ARTIFACT", f"partial artifact is present: {entry.name}")
            if not entry.is_dir() or entry.name not in _COLLECTIONS:
                _fail("ROOT_LAYOUT_INVALID", f"unexpected ledger entry: {entry.name}")
            observed_collections.add(entry.name)
            for shard in entry.iterdir():
                if _is_reparse(shard):
                    _fail("ROOT_REPARSE_POINT", f"ledger contains link/reparse point: {shard}")
                if shard.name.endswith(".tmp"):
                    _fail("PARTIAL_ARTIFACT", f"partial artifact is present: {shard.name}")
                if not shard.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", shard.name):
                    _fail("ROOT_LAYOUT_INVALID", f"unexpected collection entry: {shard.name}")
                for artifact in shard.iterdir():
                    if _is_reparse(artifact):
                        _fail("ROOT_REPARSE_POINT", f"ledger contains link/reparse point: {artifact}")
                    if artifact.name.endswith(".tmp"):
                        _fail("PARTIAL_ARTIFACT", f"partial artifact is present: {artifact.name}")
                    match = re.fullmatch(r"([0-9a-f]{64})\.json", artifact.name)
                    if not artifact.is_file() or match is None or match.group(1)[:2] != shard.name:
                        _fail("ROOT_LAYOUT_INVALID", f"unexpected artifact path: {artifact}")
                    _assert_single_link(artifact, f"final artifact {artifact.name}")
        if observed_collections != _COLLECTIONS:
            missing = sorted(_COLLECTIONS - observed_collections)
            _fail("ROOT_LAYOUT_INVALID", f"ledger collections are incomplete: {', '.join(missing)}")

    def _files(self, collection: str) -> dict[str, Path]:
        result: dict[str, Path] = {}
        directory = self.root / collection
        for shard in sorted(directory.iterdir()):
            for path in sorted(shard.iterdir()):
                digest = path.stem
                if digest in result:
                    _fail("DUPLICATE_IDENTITY", f"duplicate logical key in {collection}")
                result[digest] = path
        return result

    @staticmethod
    def _load_packet(path: Path, record_type: type[Any]) -> tuple[Any, bytes]:
        _assert_single_link(path, f"packet {path.name}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise LedgerError("STORAGE_IO", f"cannot read artifact {path.name}") from exc
        _assert_single_link(path, f"packet {path.name}")
        packet = (
            parse_prediction_json(data)
            if record_type is FrozenPredictionPacketV1
            else parse_reveal_json(data)
        )
        if data != packet_bytes(packet):
            _fail("NONCANONICAL_ARTIFACT", f"artifact bytes are noncanonical or tampered: {path.name}")
        return packet, data

    @staticmethod
    def _validate_receipt(
        receipt: ImmutableReceiptV1,
        packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1,
        logical_digest: str,
        packet_data: bytes,
        relative_path: str,
    ) -> None:
        if receipt.receipt_schema_version != RECEIPT_SCHEMA or receipt.record_type != "IMMUTABLE_PACKET_RECEIPT":
            _fail("RECEIPT_MISMATCH", "receipt schema is invalid")
        if receipt.packet_type != packet.packet_type:
            _fail("RECEIPT_MISMATCH", "receipt packet type does not match")
        _require_hash(receipt.logical_key_digest, "receipt.logical_key_digest")
        _require_hash(receipt.canonical_fingerprint, "receipt.canonical_fingerprint")
        _require_hash(receipt.immutable_receipt_id, "receipt.immutable_receipt_id")
        _require_hash(receipt.stored_bytes_sha256, "receipt.stored_bytes_sha256")
        _require_hash(receipt.stored_bytes_fingerprint, "receipt.stored_bytes_fingerprint")
        if receipt.logical_key_digest != logical_digest:
            _fail("RECEIPT_MISMATCH", "receipt logical key does not match")
        if receipt.canonical_fingerprint != packet.canonical_fingerprint:
            _fail("RECEIPT_MISMATCH", "receipt fingerprint does not match packet")
        if receipt.immutable_receipt_id != packet.immutable_receipt_id:
            _fail("RECEIPT_MISMATCH", "receipt identity does not match packet")
        if receipt.immutable_receipt_id != _receipt_id(
            packet.packet_type, logical_digest, packet.canonical_fingerprint
        ):
            _fail("RECEIPT_MISMATCH", "receipt identity derivation does not match")
        if receipt.packet_relative_path != relative_path:
            _fail("RECEIPT_MISMATCH", "receipt packet path binding does not match")
        if receipt.stored_bytes_sha256 != _stored_bytes_sha256(packet_data):
            _fail("RECEIPT_MISMATCH", "receipt stored-byte hash does not match")
        if receipt.stored_bytes_fingerprint != _stored_bytes_fingerprint(
            packet.packet_type, packet_data
        ):
            _fail("RECEIPT_MISMATCH", "receipt domain-separated stored-byte fingerprint does not match")
        if receipt.terminal_write_result != "CREATED_IMMUTABLE":
            _fail("RECEIPT_MISMATCH", "receipt terminal result is invalid")

    def _load_collection(
        self,
        packet_collection: str,
        receipt_collection: str,
        record_type: type[FrozenPredictionPacketV1] | type[OutcomeRevealPacketV1],
    ) -> dict[str, StoredArtifact]:
        packet_files = self._files(packet_collection)
        receipt_files = self._files(receipt_collection)
        if set(packet_files) != set(receipt_files):
            _fail("ORPHAN_ARTIFACT", f"{packet_collection} packet/receipt set differs")
        result: dict[str, StoredArtifact] = {}
        for logical_digest in sorted(packet_files):
            packet_path = packet_files[logical_digest]
            receipt_path = receipt_files[logical_digest]
            packet, packet_data = self._load_packet(packet_path, record_type)
            expected_digest = (
                prediction_logical_key_digest(packet)
                if isinstance(packet, FrozenPredictionPacketV1)
                else reveal_logical_key_digest(packet)
            )
            if logical_digest != expected_digest:
                _fail("ROOT_LAYOUT_INVALID", "artifact path does not match logical key")
            try:
                _assert_single_link(receipt_path, f"receipt {receipt_path.name}")
                receipt_data = receipt_path.read_bytes()
            except OSError as exc:
                raise LedgerError("STORAGE_IO", f"cannot read receipt {receipt_path.name}") from exc
            _assert_single_link(receipt_path, f"receipt {receipt_path.name}")
            receipt = _receipt_from_json(receipt_data)
            if receipt_data != _canonical_json(receipt, newline=True):
                _fail("NONCANONICAL_ARTIFACT", f"receipt bytes are noncanonical: {receipt_path.name}")
            self._validate_receipt(
                receipt,
                packet,
                logical_digest,
                packet_data,
                packet_path.relative_to(self.root).as_posix(),
            )
            result[logical_digest] = StoredArtifact(
                packet=packet,
                receipt=receipt,
                packet_path=packet_path,
                receipt_path=receipt_path,
                created=False,
                idempotent=False,
            )
        return result

    def _reload(self) -> None:
        self._validate_layout()
        predictions = self._load_collection(
            _PREDICTION_COLLECTION,
            _PREDICTION_RECEIPT_COLLECTION,
            FrozenPredictionPacketV1,
        )
        reveals = self._load_collection(
            _REVEAL_COLLECTION,
            _REVEAL_RECEIPT_COLLECTION,
            OutcomeRevealPacketV1,
        )
        predictions_by_fingerprint: dict[str, StoredArtifact] = {}
        for stored in predictions.values():
            fingerprint = stored.packet.canonical_fingerprint
            if fingerprint in predictions_by_fingerprint:
                _fail("DUPLICATE_IDENTITY", "prediction fingerprint is duplicated")
            predictions_by_fingerprint[fingerprint] = stored
        for stored in reveals.values():
            reveal = stored.packet
            if not isinstance(reveal, OutcomeRevealPacketV1):
                _fail("INVALID_SCHEMA", "reveal collection contains a non-reveal packet")
            prediction = predictions_by_fingerprint.get(reveal.original_prediction_fingerprint)
            if prediction is None:
                _fail("PREDICTION_REFERENCE_MISMATCH", "reveal references missing prediction")
            self._validate_reveal_reference(reveal, prediction.packet)
        self._predictions = predictions
        self._reveals = reveals

    @staticmethod
    def _validate_reveal_reference(
        reveal: OutcomeRevealPacketV1,
        prediction: FrozenPredictionPacketV1 | OutcomeRevealPacketV1,
    ) -> None:
        if not isinstance(prediction, FrozenPredictionPacketV1):
            _fail("PREDICTION_REFERENCE_MISMATCH", "reveal target is not a prediction")
        validate_frozen_prediction_packet(prediction)
        validate_outcome_reveal_packet(reveal)
        if (
            reveal.original_prediction_fingerprint != prediction.canonical_fingerprint
            or reveal.original_prediction_receipt_id != prediction.immutable_receipt_id
            or _plain(reveal.research_protocol_id) != _plain(prediction.research_protocol_id)
            or _plain(reveal.research_opportunity_id) != _plain(prediction.research_opportunity_id)
        ):
            _fail("PREDICTION_REFERENCE_MISMATCH", "reveal does not exactly reference prediction")
        prediction_cutoff = _parse_utc(prediction.prediction_cutoff_at, "prediction_cutoff_at")
        outcome_cutoff = _parse_utc(reveal.outcome_cutoff_at, "outcome_cutoff_at")
        resolved = _parse_utc(reveal.outcome_resolved_at, "outcome_resolved_at")
        if outcome_cutoff <= prediction_cutoff or resolved <= prediction_cutoff:
            _fail("INVALID_CHRONOLOGY", "outcome chronology is not strictly after prediction")
        for index, evidence in enumerate(reveal.outcome_evidence):
            available = _parse_utc(evidence["available_at"], f"outcome_evidence[{index}].available_at")
            if available <= prediction_cutoff or available > outcome_cutoff:
                _fail("INVALID_CHRONOLOGY", "outcome evidence is outside reveal chronology")
        retrieved = _parse_utc(reveal.outcome_provenance["retrieved_at"], "outcome_provenance.retrieved_at")
        if retrieved <= prediction_cutoff or retrieved > outcome_cutoff:
            _fail("INVALID_CHRONOLOGY", "outcome provenance retrieval is outside reveal chronology")

    def _write_exclusive(self, target: Path, data: bytes) -> None:
        self._ensure_contained(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_contained(target)
        temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp")
        self._ensure_contained(temporary)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                _assert_single_link(target, f"existing final artifact {target.name}")
                if target.read_bytes() != data:
                    _fail("IMMUTABLE_CONFLICT", f"conflicting immutable artifact: {target.name}")
                _assert_single_link(target, f"existing final artifact {target.name}")
            finally:
                temporary.unlink(missing_ok=True)
            _fsync_directory(target.parent)
        except LedgerError:
            raise
        except OSError as exc:
            raise LedgerError("STORAGE_IO", f"exclusive artifact creation failed: {target.name}") from exc

    def _receipt_for(
        self,
        packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1,
        logical_digest: str,
        packet_path: Path,
        data: bytes,
    ) -> ImmutableReceiptV1:
        return ImmutableReceiptV1(
            receipt_schema_version=RECEIPT_SCHEMA,
            record_type="IMMUTABLE_PACKET_RECEIPT",
            packet_type=packet.packet_type,
            logical_key_digest=logical_digest,
            canonical_fingerprint=packet.canonical_fingerprint,
            immutable_receipt_id=packet.immutable_receipt_id,
            packet_relative_path=packet_path.relative_to(self.root).as_posix(),
            stored_bytes_sha256=_stored_bytes_sha256(data),
            stored_bytes_fingerprint=_stored_bytes_fingerprint(packet.packet_type, data),
            terminal_write_result="CREATED_IMMUTABLE",
        )

    def _store(
        self,
        packet: FrozenPredictionPacketV1 | OutcomeRevealPacketV1,
        packet_collection: str,
        receipt_collection: str,
        logical_digest: str,
    ) -> StoredArtifact:
        self._reload()
        data = packet_bytes(packet)
        packet_path = self._artifact_path(packet_collection, logical_digest)
        receipt_path = self._artifact_path(receipt_collection, logical_digest)
        existing = self._predictions.get(logical_digest) or self._reveals.get(logical_digest)
        if existing is not None:
            if existing.packet_path != packet_path or existing.receipt_path != receipt_path:
                _fail("ROOT_LAYOUT_INVALID", "logical key collides across packet collections")
            if existing.packet_path.read_bytes() != data:
                _fail("IMMUTABLE_CONFLICT", "logical identity already has different bytes")
            return replace(existing, created=False, idempotent=True)
        receipt = self._receipt_for(packet, logical_digest, packet_path, data)
        self._write_exclusive(packet_path, data)
        self._write_exclusive(receipt_path, _canonical_json(receipt, newline=True))
        self._reload()
        stored = self._predictions.get(logical_digest) or self._reveals.get(logical_digest)
        if stored is None:
            _fail("STORAGE_IO", "new immutable artifact was not visible after validation")
        return replace(stored, created=True, idempotent=False)

    def freeze_prediction(self, packet: FrozenPredictionPacketV1) -> StoredArtifact:
        validate_frozen_prediction_packet(packet)
        return self._store(
            packet,
            _PREDICTION_COLLECTION,
            _PREDICTION_RECEIPT_COLLECTION,
            prediction_logical_key_digest(packet),
        )

    def reveal_outcome(self, packet: OutcomeRevealPacketV1) -> StoredArtifact:
        validate_outcome_reveal_packet(packet)
        self._reload()
        prediction = next(
            (
                stored
                for stored in self._predictions.values()
                if stored.packet.canonical_fingerprint == packet.original_prediction_fingerprint
            ),
            None,
        )
        if prediction is None:
            _fail("PREDICTION_REFERENCE_MISMATCH", "referenced prediction is absent")
        self._validate_reveal_reference(packet, prediction.packet)
        return self._store(
            packet,
            _REVEAL_COLLECTION,
            _REVEAL_RECEIPT_COLLECTION,
            reveal_logical_key_digest(packet),
        )

    def read_prediction(self, logical_key_digest: str) -> StoredArtifact:
        _require_hash(logical_key_digest, "logical_key_digest")
        self._reload()
        try:
            return self._predictions[logical_key_digest]
        except KeyError as exc:
            raise LedgerError("PREDICTION_NOT_FOUND", "prediction logical key is absent") from exc

    def read_reveal(self, logical_key_digest: str) -> StoredArtifact:
        _require_hash(logical_key_digest, "logical_key_digest")
        self._reload()
        try:
            return self._reveals[logical_key_digest]
        except KeyError as exc:
            raise LedgerError("REVEAL_NOT_FOUND", "reveal logical key is absent") from exc


def _synthetic_identity(scope: str, identity: str, marker: str) -> dict[str, Any]:
    return {
        "owner_scope": scope,
        "owner_identity": identity,
        "fingerprint": hashlib.sha256(f"{scope}:{identity}".encode("utf-8")).hexdigest(),
        "state": "SYNTHETIC",
        "fixture_identity": marker,
    }


def _test1_prediction(*, reason: str = "synthetic watch observation") -> FrozenPredictionPacketV1:
    fixture = "TEST1-FIXTURE-V1"
    evidence = tuple(
        {
            "owner_scope": "SYNTHETIC_EVIDENCE",
            "evidence_id": f"TEST1-EVIDENCE-{letter}",
            "fingerprint": hashlib.sha256(f"TEST1:{letter}".encode("ascii")).hexdigest(),
            "available_at": f"2026-08-29T13:5{index}:00Z",
            "provenance_locator": f"synthetic://TEST1/{letter}",
            "state": "SYNTHETIC",
            "fixture_identity": fixture,
        }
        for index, letter in enumerate(("A", "B", "C"), start=1)
    )
    missingness = (
        {"field": "observed-input", "state": "OBSERVED", "value": 1, "evidence_ids": ("TEST1-EVIDENCE-A",)},
        {"field": "missing-input", "state": "MISSING", "reason": "source field absent"},
        {"field": "unavailable-input", "state": "UNAVAILABLE", "reason": "source did not publish"},
        {"field": "unknown-input", "state": "UNKNOWN", "reason": "truth cannot be established"},
        {"field": "not-applicable-input", "state": "NOT_APPLICABLE", "reason": "contract does not apply"},
        {
            "field": "reconstructed-input",
            "state": "RECONSTRUCTED",
            "value": 2,
            "evidence_ids": ("TEST1-EVIDENCE-A", "TEST1-EVIDENCE-B"),
            "reconstruction_method": "synthetic deterministic sum",
            "source_inputs": ("TEST1-EVIDENCE-A", "TEST1-EVIDENCE-B"),
            "reconstructed_at": "2026-08-29T13:59:00Z",
            "non_recorded": True,
        },
        {
            "field": "synthetic-input",
            "state": "SYNTHETIC",
            "value": 3,
            "evidence_ids": ("TEST1-EVIDENCE-C",),
            "fixture_identity": fixture,
        },
    )
    return build_frozen_prediction_packet(
        research_protocol_id=_synthetic_identity("RESEARCH_PROTOCOL", "TEST1-PROTOCOL-V1", fixture),
        research_opportunity_id=_synthetic_identity("STAT_DATA_OPPORTUNITY", "TEST1-OPPORTUNITY-V1", fixture),
        symbol_entity_ref={
            "state": "SYNTHETIC",
            "value": {"symbol": "TEST1", "entity_identity": "TEST1-ENTITY"},
            "fixture_identity": fixture,
        },
        event_ref={"state": "NOT_APPLICABLE", "reason": "synthetic current-edge observation"},
        prediction_cutoff_at="2026-08-29T14:00:00Z",
        evidence_availability_cutoff_at="2026-08-29T14:00:00Z",
        source_evidence_refs=evidence,
        code_identity=_synthetic_identity("GIT_SOURCE", "848d20a6bd5a49e9bb8e179eaa374109756801b0", fixture),
        strategy_identity=_synthetic_identity("STRATEGY_PROFILE", "TEST1-STRATEGY-V1", fixture),
        configuration_identity=_synthetic_identity("CONFIGURATION", "TEST1-CONFIG-V1", fixture),
        runtime_identity=_synthetic_identity("OFFLINE_RUNTIME", "TEST1-RUNTIME-V1", fixture),
        feature_observations=(
            {
                "observation_id": "TEST1-OBSERVATION",
                "state": "SYNTHETIC",
                "value": "WATCH",
                "evidence_ids": ("TEST1-EVIDENCE-A", "TEST1-EVIDENCE-B", "TEST1-EVIDENCE-C"),
                "fixture_identity": fixture,
            },
        ),
        research_predictions=(),
        uncertainty={"state": "NOT_SUPPLIED", "reason": "WATCH observation has no probability claim"},
        abstention_rejection_state={"state": "WATCH", "reasons": (reason,)},
        missingness_ledger=missingness,
        outcome_state="UNRESOLVED",
        created_at="2026-08-29T14:00:01Z",
    )


def _test1_reveal(
    prediction: FrozenPredictionPacketV1,
    *,
    outcome_value: float = 1.25,
    outcome_cutoff_at: str = "2026-08-29T14:10:00Z",
    outcome_resolved_at: str = "2026-08-29T14:06:00Z",
) -> OutcomeRevealPacketV1:
    fixture = "TEST1-FIXTURE-V1"
    evidence_id = "TEST1-EVIDENCE-D"
    return build_outcome_reveal_packet(
        original_prediction_fingerprint=prediction.canonical_fingerprint,
        original_prediction_receipt_id=prediction.immutable_receipt_id,
        research_protocol_id=prediction.research_protocol_id,
        research_opportunity_id=prediction.research_opportunity_id,
        outcome_cutoff_at=outcome_cutoff_at,
        outcome_resolved_at=outcome_resolved_at,
        outcome_evidence=(
            {
                "owner_scope": "SYNTHETIC_EVIDENCE",
                "evidence_id": evidence_id,
                "fingerprint": hashlib.sha256(b"TEST1:D").hexdigest(),
                "available_at": "2026-08-29T14:05:00Z",
                "provenance_locator": "synthetic://TEST1/D",
                "state": "SYNTHETIC",
                "fixture_identity": fixture,
            },
        ),
        outcome_provenance={
            "source_identity": _synthetic_identity("OUTCOME_SOURCE", "TEST1-SOURCE-V1", fixture),
            "retrieved_at": "2026-08-29T14:07:00Z",
            "transformation_identity": _synthetic_identity("OUTCOME_TRANSFORM", "TEST1-TRANSFORM-V1", fixture),
            "admissibility_state": "ADMITTED",
        },
        outcome_semantic_id=_synthetic_identity("OUTCOME_SEMANTIC", "TEST1-RETURN-R-V1", fixture),
        outcome_semantic_version="V1",
        outcome_values=(
            {
                "outcome_id": "TEST1-EXECUTABLE-R",
                "state": "SYNTHETIC",
                "value": outcome_value,
                "evidence_ids": (evidence_id,),
                "fixture_identity": fixture,
            },
        ),
        created_at="2026-08-29T14:11:00Z",
    )


def _expect_category(category: str, operation: Any) -> None:
    try:
        operation()
    except LedgerError as exc:
        if exc.category != category:
            raise AssertionError(f"expected {category}, got {exc.category}") from exc
        return
    raise AssertionError(f"expected ledger failure {category}")


def _prove(condition: bool, message: str) -> None:
    if not condition:
        _fail("DEMONSTRATION_PROOF_FAILED", message)


def _module_imports_are_stdlib_only() -> bool:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {
        "__future__",
        "ast",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "subprocess",
        "sys",
        "tempfile",
        "types",
        "typing",
        "uuid",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported <= allowed


def _no_production_consumer_imports() -> bool:
    module_name = "current_edge_research_ledger"
    package_dir = Path(__file__).resolve().parent
    for path in package_dir.glob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        if module_name in path.read_text(encoding="utf-8", errors="strict"):
            return False
    return True


def run_synthetic_demonstration(root: str | Path) -> dict[str, Any]:
    """Run deterministic TEST1 proof and return truths only after direct checks."""

    demonstration_root = Path(root)
    if not demonstration_root.is_absolute() or ".." in demonstration_root.parts:
        _fail("ROOT_PATH_INVALID", "demonstration root must be absolute without traversal")
    demonstration_root.mkdir(parents=True, exist_ok=True)
    prediction = _test1_prediction()
    ledger = CurrentEdgeResearchLedger(demonstration_root / "happy")
    stored_prediction = ledger.freeze_prediction(prediction)
    p1_bytes = stored_prediction.packet_path.read_bytes()
    p1_receipt_bytes = stored_prediction.receipt_path.read_bytes()
    p1_fingerprint = prediction.canonical_fingerprint
    identical_prediction = ledger.freeze_prediction(_test1_prediction())
    _prove(identical_prediction.idempotent, "prediction duplicate was not idempotent")
    _prove(
        identical_prediction.packet_path.read_bytes() == p1_bytes,
        "prediction bytes changed after identical freeze",
    )
    _prove(
        identical_prediction.receipt_path.read_bytes() == p1_receipt_bytes,
        "prediction receipt changed after identical freeze",
    )

    restarted = CurrentEdgeResearchLedger(demonstration_root / "happy")
    restarted_prediction = restarted.read_prediction(prediction_logical_key_digest(prediction))
    _prove(
        restarted_prediction.packet_path.read_bytes() == p1_bytes,
        "prediction bytes changed on in-process restart",
    )
    _prove(
        restarted_prediction.receipt_path.read_bytes() == p1_receipt_bytes,
        "prediction receipt changed on in-process restart",
    )
    restart_script = (
        "import json,sys; import momentum_hunter.current_edge_research_ledger as m; "
        "s=m.CurrentEdgeResearchLedger(sys.argv[1]); p=s.read_prediction(sys.argv[2]); "
        "print(json.dumps({'bytes':m._stored_bytes_sha256(p.packet_path.read_bytes()),"
        "'fingerprint':p.packet.canonical_fingerprint,'receipt':p.packet.immutable_receipt_id},sort_keys=True))"
    )
    clean_restart = subprocess.run(
        [
            sys.executable,
            "-c",
            restart_script,
            str((demonstration_root / "happy").resolve()),
            prediction_logical_key_digest(prediction),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    clean_restart_proof = json.loads(clean_restart.stdout)
    _prove(
        clean_restart_proof
        == {
            "bytes": _stored_bytes_sha256(p1_bytes),
            "fingerprint": p1_fingerprint,
            "receipt": prediction.immutable_receipt_id,
        },
        "clean-process restart did not reproduce P1",
    )
    reveal = _test1_reveal(prediction)
    stored_reveal = restarted.reveal_outcome(reveal)
    o1_bytes = stored_reveal.packet_path.read_bytes()
    o1_receipt_bytes = stored_reveal.receipt_path.read_bytes()
    identical_reveal = restarted.reveal_outcome(_test1_reveal(prediction))
    _prove(identical_reveal.idempotent, "reveal duplicate was not idempotent")
    _prove(
        stored_reveal.packet.original_prediction_fingerprint == p1_fingerprint,
        "reveal does not reference exact P1",
    )
    _prove(
        restarted_prediction.packet_path.read_bytes() == p1_bytes,
        "P1 bytes changed after reveal",
    )
    _prove(
        restarted_prediction.packet.canonical_fingerprint == p1_fingerprint,
        "P1 fingerprint changed after reveal",
    )
    _prove(b"TEST1-EVIDENCE-D" not in p1_bytes, "future evidence D leaked into P1")
    _prove(
        b"TEST1-EVIDENCE-D" in o1_bytes,
        "future evidence D is absent from reveal",
    )

    _expect_category(
        "IMMUTABLE_CONFLICT",
        lambda: restarted.freeze_prediction(_test1_prediction(reason="conflicting watch reason")),
    )
    _expect_category(
        "IMMUTABLE_CONFLICT",
        lambda: restarted.reveal_outcome(_test1_reveal(prediction, outcome_value=-1.0)),
    )
    _prove(
        restarted_prediction.packet_path.read_bytes() == p1_bytes,
        "conflict attempts changed P1 bytes",
    )
    _prove(
        restarted_prediction.receipt_path.read_bytes() == p1_receipt_bytes,
        "conflict attempts changed P1 receipt",
    )

    future_kwargs = _plain(_test1_prediction())
    future_kwargs["source_evidence_refs"][0]["available_at"] = "2026-08-29T14:00:01Z"
    for name in ("packet_schema_version", "packet_type", "research_only", "production_decision_authority", "execution_authority", "canonical_fingerprint", "immutable_receipt_id"):
        future_kwargs.pop(name)
    _expect_category("FUTURE_EVIDENCE", lambda: build_frozen_prediction_packet(**future_kwargs))

    _expect_category(
        "INVALID_CHRONOLOGY",
        lambda: restarted.reveal_outcome(
            _test1_reveal(
                prediction,
                outcome_cutoff_at="2026-08-29T13:59:59Z",
                outcome_resolved_at="2026-08-29T13:59:58Z",
            )
        ),
    )

    tamper_ledger = CurrentEdgeResearchLedger(demonstration_root / "tamper")
    tampered = tamper_ledger.freeze_prediction(prediction)
    tampered.packet_path.write_bytes(tampered.packet_path.read_bytes().replace(b"WATCH", b"ABSTAINED"))
    _expect_category(
        "FINGERPRINT_MISMATCH",
        lambda: CurrentEdgeResearchLedger(demonstration_root / "tamper"),
    )

    escape_parent = demonstration_root / "escape-case"
    inside = escape_parent / "inside"
    outside = escape_parent / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"UNCHANGED")
    _expect_category(
        "ROOT_PATH_INVALID",
        lambda: CurrentEdgeResearchLedger(inside / ".." / "outside"),
    )
    _prove(sentinel.read_bytes() == b"UNCHANGED", "root escape attempt changed outside sentinel")

    all_paths_contained = all(
        path.resolve(strict=False).is_relative_to(demonstration_root.resolve(strict=True))
        for path in demonstration_root.rglob("*")
    )
    structural = (
        _module_imports_are_stdlib_only()
        and _no_production_consumer_imports()
        and not any(
            hasattr(CurrentEdgeResearchLedger, name)
            for name in ("update", "delete", "mutate", "execute", "submit_order", "start_service")
        )
    )
    _prove(all_paths_contained, "demonstration wrote outside caller root")
    _prove(structural, "module structural no-authority proof failed")

    truths = {
        "PREDICT_FIRST_FREEZE_REVEAL_LATER": True,
        "PREDICTION_MUTATED_AFTER_FREEZE": False,
        "PREDICTION_MUTATED_AFTER_REVEAL": False,
        "CONFLICTING_DUPLICATE_ACCEPTED": False,
        "FUTURE_EVIDENCE_ACCEPTED_AT_FREEZE": False,
        "INVALID_CHRONOLOGY_ACCEPTED": False,
        "TAMPERING_UNDETECTED": False,
        "ROOT_ESCAPE_POSSIBLE": False,
        "PRODUCTION_WRITE_PATH": "NONE",
        "PRODUCTION_DECISION_AUTHORITY": PRODUCTION_DECISION_AUTHORITY,
        "EXECUTION_AUTHORITY": EXECUTION_AUTHORITY,
        "NEW_DATABASE_REQUIRED": False,
        "NEW_SERVICE_REQUIRED": False,
        "ROLLBACK_REQUIRES_PRODUCTION_REPAIR": False,
    }
    return {
        "experiment": "TEST1",
        "lifecycle": "OBSERVE->FREEZE->RESTART->WAIT->REVEAL->COMPARE",
        "prediction_logical_key_digest": prediction_logical_key_digest(prediction),
        "prediction_fingerprint": prediction.canonical_fingerprint,
        "prediction_receipt_id": prediction.immutable_receipt_id,
        "prediction_stored_bytes_sha256": _stored_bytes_sha256(p1_bytes),
        "prediction_stored_bytes_fingerprint": _stored_bytes_fingerprint(
            prediction.packet_type, p1_bytes
        ),
        "prediction_receipt_stored_bytes_sha256": _stored_bytes_sha256(p1_receipt_bytes),
        "reveal_logical_key_digest": reveal_logical_key_digest(reveal),
        "reveal_fingerprint": reveal.canonical_fingerprint,
        "reveal_receipt_id": reveal.immutable_receipt_id,
        "reveal_stored_bytes_sha256": _stored_bytes_sha256(o1_bytes),
        "reveal_stored_bytes_fingerprint": _stored_bytes_fingerprint(reveal.packet_type, o1_bytes),
        "reveal_receipt_stored_bytes_sha256": _stored_bytes_sha256(o1_receipt_bytes),
        "clean_restart_process_proof": clean_restart_proof,
        "truths": truths,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="argus-current-edge-ledger-demo-") as temporary:
        result = run_synthetic_demonstration(Path(temporary).resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
