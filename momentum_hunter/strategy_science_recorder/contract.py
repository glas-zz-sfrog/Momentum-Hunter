"""Strict, provider-free consumer view of the approved recorder contract.

``ResearchExportEnvelopeV1`` remains a proposed shared cross-lane interface.
The parser here is intentionally a Science-only offline reference consumer; it
does not claim natural producer compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Mapping

from .canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    owner_identity,
    parse_rfc3339,
    recorder_identity,
    require_sha256,
    sha256_hex,
    strict_json_loads,
)


SCHEMA_VERSION = "1.0.0"
SCHEMA_MAJOR_VERSION = 1
SOURCE_CONTRACT = "ResearchExportEnvelopeV1"
PREDECESSOR_SCHEMA_VERSION = "1.0.0-proposal"
SCIENCE_OFFLINE_EXPORT_PROFILE = "ARGUS_SCIENCE_OFFLINE_RESEARCH_EXPORT_V1"
HASH_ALGORITHM = "SHA-256"
HASH_UNIT = "EXACT_CANONICAL_UTF8_JSON_BYTES_WITH_LF"
PREVIOUS_HASH_TARGET = "EXACT_PRIOR_RAW_SOURCE_ENVELOPE_BYTES"
SOURCE_SEQUENCE_SCOPE = "PER_STREAM_CONTIGUOUS_FROM_ONE"
AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
GENESIS_SHA256 = "0" * 64

BASE_CANONICAL_SHA = "986407467ae8de27df1bc228d843a8701014ac06"
PREDECESSOR_DIRECTIVE = "ARGUS-SCIENCE-ALWAYS-ON-RECORDER-CONTRACT-001"
PREDECESSOR_SIDECAR_SHA256 = (
    "f40207a300b0d5ea91992e4e7f03491e3de031714a8928d01118a8a9b9ec4434"
)
PREDECESSOR_SCHEMA_SHA256 = (
    "f8b739ef7738b5e64bfd86b52b0a3f7d3b50fd006cb60a66954c206d276a0a40"
)

EVENT_TYPES = frozenset(
    {
        "DISCOVERY_CYCLE",
        "DECISION_FACT",
        "MARKET_FACT",
        "PROVIDER_HEALTH",
        "SESSION_MANIFEST",
    }
)
RECORD_FAMILIES = (
    "discovery-cycle",
    "candidate-observation",
    "decision-event",
    "market-snapshot",
    "reference-plan",
    "provider-health-event",
    "outcome-observation",
)
EVENT_CHANNEL = {
    "DISCOVERY_CYCLE": "discovery",
    "DECISION_FACT": "decision",
    "MARKET_FACT": "market",
    "PROVIDER_HEALTH": "health",
    "SESSION_MANIFEST": "session",
}
AVAILABILITY_STATES = frozenset(
    {
        "PRESENT",
        "UNAVAILABLE",
        "NOT_APPLICABLE",
        "NOT_OBSERVED",
        "PROVIDER_FAILED",
        "CAPACITY_EXCLUDED",
        "SESSION_TRUNCATED",
        "STALE",
        "PARTIAL",
        "FAILED",
        "UNKNOWN",
    }
)
HORIZONS = (
    "PLUS_5M",
    "PLUS_15M",
    "PLUS_30M",
    "PLUS_60M",
    "SESSION_CLOSE",
    "MFE",
    "MAE",
)
TERMINAL_OUTCOME_STATES = frozenset(
    {
        "UNAVAILABLE",
        "NOT_APPLICABLE",
        "NOT_OBSERVED",
        "PROVIDER_FAILED",
        "CAPACITY_EXCLUDED",
        "SESSION_TRUNCATED",
        "FAILED",
    }
)
PROVIDER_DERIVED_TERMINAL_OUTCOME_STATES = frozenset(
    {"UNAVAILABLE", "NOT_OBSERVED", "PROVIDER_FAILED", "FAILED"}
)

TIME_NORMALIZATION_RULE = "ARGUS_TIME_IDENTITY_V1"
TIME_ROLES = frozenset(
    {
        "SOURCE_EVENT_TIME",
        "SOURCE_PUBLICATION_TIME",
        "PROVIDER_KNOWN_AT",
        "PROVIDER_RECEIVED_AT",
        "DISCOVERY_TIME",
        "DECISION_TIME",
        "DECISION_CUTOFF",
        "RECORDER_CAPTURE_TIME",
        "OUTCOME_TIME",
    }
)

_DECIMAL_STRING = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_VERSION_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*")

_PROHIBITED_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "authorization_header",
        "authorization",
        "api_key",
        "api_secret",
        "client_secret",
        "cookie",
        "session_cookie",
        "secret",
        "password",
        "token",
        "credential",
        "credentials",
        "account_hash",
        "account_number",
        "position",
        "positions",
        "order",
        "orders",
        "broker",
        "paper_authority",
        "shadow_authority",
        "execution_endpoint",
        "provider_credentials",
    }
)

_PROHIBITED_NORMALIZED_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", item.casefold())
    for item in _PROHIBITED_KEYS
) | frozenset(
    {
        "accountid",
        "accountnumber",
        "accounttoken",
        "apikey",
        "apisecret",
        "authorizationheader",
        "brokerid",
        "brokerorder",
        "clientsecret",
        "executioncommand",
        "executionendpoint",
        "executionpolicy",
        "executionrequest",
        "orderid",
        "orderrequest",
        "orderside",
        "paperauthority",
        "providercredentials",
        "refreshtoken",
        "shadowauthority",
    }
)


class RecorderContractError(ValueError):
    """Raised when external bytes cannot be admitted to Science custody."""


@dataclass(frozen=True)
class ValidatedExportEnvelope:
    raw_bytes: bytes
    raw_sha256: str
    schema_version: str
    event_type: str
    stream_id: str
    session_id: Mapping[str, object]
    source_owner_identity: str
    source_interface_identity: str
    source_contract: str
    source_contract_version: str
    source_event_id: str
    source_event_fingerprint_sha256: str
    source_sequence: int
    event_time: str
    effective_known_at: str
    emitted_at: str
    previous_record_sha256: str
    payload_sha256: str
    payload: Mapping[str, object]

    @property
    def channel(self) -> str:
        return EVENT_CHANNEL[self.event_type]


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise RecorderContractError(f"Required field is missing: {field}.")
    return mapping[field]


def _text(mapping: Mapping[str, object], field: str) -> str:
    value = _required(mapping, field)
    if not isinstance(value, str) or not value:
        raise RecorderContractError(f"{field} must be a nonempty string.")
    return value


def require_exact_fields(
    value: object,
    *,
    required: frozenset[str] | set[str],
    optional: frozenset[str] | set[str] = frozenset(),
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecorderContractError(f"{label} must be an object.")
    actual = set(value)
    missing = set(required).difference(actual)
    unknown = actual.difference(set(required).union(optional))
    if missing or unknown:
        raise RecorderContractError(
            f"{label} has missing or unknown fields; missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}."
        )
    return value


def require_integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecorderContractError(f"{label} must be an integer >= {minimum}.")
    return value


def require_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RecorderContractError(f"{label} must be a boolean.")
    return value


def require_decimal_string(value: object, label: str) -> str:
    if not isinstance(value, str) or _DECIMAL_STRING.fullmatch(value) is None:
        raise RecorderContractError(f"{label} must be a canonical decimal string.")
    try:
        Decimal(value)
    except InvalidOperation as exc:
        raise RecorderContractError(f"{label} is not a finite decimal string.") from exc
    return value


def require_versioned_reason(value: object, label: str) -> Mapping[str, object]:
    reason = require_exact_fields(
        value,
        required={"code", "version"},
        label=label,
    )
    for field in ("code", "version"):
        item = reason[field]
        if not isinstance(item, str) or _VERSION_TEXT.fullmatch(item) is None:
            raise RecorderContractError(f"{label}.{field} must be versioned text.")
    return reason


def _walk_prohibited(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized in _PROHIBITED_NORMALIZED_KEYS:
                raise RecorderContractError(
                    f"Prohibited authority/capability field at {path}.{key}."
                )
            _walk_prohibited(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_prohibited(child, f"{path}[{index}]")


def reject_prohibited_fields(value: object, path: str = "$") -> None:
    """Reject normalized secret/account/order/execution field-name variants."""

    _walk_prohibited(value, path)


def require_identity(
    value: object,
    label: str,
    *,
    kinds: frozenset[str] | None = None,
    allow_recorder_allocated: bool = False,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecorderContractError(f"{label} must be an identity object.")
    mode = value.get("allocation_mode")
    kind = value.get("identity_kind")
    if not isinstance(kind, str) or (kinds is not None and kind not in kinds):
        raise RecorderContractError(f"{label} has an invalid identity kind.")
    if mode == "OWNER_WRAPPED":
        require_exact_fields(
            value,
            required={
                "allocation_mode",
                "identity_kind",
                "identity_version",
                "owner_id",
                "owner_namespace",
                "owner_schema_version",
                "recorder_id",
            },
            label=label,
        )
        expected = owner_identity(
            kind,
            str(value["owner_namespace"]),
            str(value["owner_id"]),
            owner_schema_version=str(value["owner_schema_version"]),
        )
    elif mode == "RECORDER_DURABLE_ALLOCATED":
        if not allow_recorder_allocated:
            raise RecorderContractError(
                f"{label} requires OWNER_WRAPPED identity at the external custody boundary."
            )
        require_exact_fields(
            value,
            required={
                "allocation_mode",
                "identity_kind",
                "identity_version",
                "logical_key",
                "logical_key_fingerprint_sha256",
                "recorder_id",
            },
            label=label,
        )
        logical_key = value.get("logical_key")
        if not isinstance(logical_key, Mapping) or not logical_key:
            raise RecorderContractError(f"{label}.logical_key must be a nonempty object.")
        expected = recorder_identity(kind, logical_key)
    else:
        raise RecorderContractError(f"{label} has unsupported allocation_mode.")
    if dict(value) != expected:
        raise RecorderContractError(f"{label} does not match its frozen logical key.")
    return value


def require_evidence_value(
    value: object,
    label: str,
    *,
    value_kind: str | None = None,
    identity_kinds: frozenset[str] | None = None,
) -> Mapping[str, object]:
    evidence = require_exact_fields(
        value,
        required={"state", "authority", "reason_code"},
        optional={"value", "source_record_id", "source_fingerprint_sha256"},
        label=label,
    )
    state = _text(evidence, "state")
    if state not in AVAILABILITY_STATES:
        raise RecorderContractError(f"{label}.state is unsupported.")
    _text(evidence, "authority")
    reason = _text(evidence, "reason_code")
    if state == "PRESENT":
        if "value" not in evidence or reason != "PRESENT":
            raise RecorderContractError(f"{label} PRESENT requires value and PRESENT reason.")
    elif "value" in evidence:
        raise RecorderContractError(f"{label} non-PRESENT state prohibits value.")
    if "source_fingerprint_sha256" in evidence:
        require_sha256(evidence["source_fingerprint_sha256"], f"{label}.source_fingerprint_sha256")
    if "source_record_id" in evidence:
        source = evidence["source_record_id"]
        if isinstance(source, Mapping):
            require_identity(source, f"{label}.source_record_id")
        elif not isinstance(source, str) or not source:
            raise RecorderContractError(f"{label}.source_record_id must be an identity or text.")
    if state == "PRESENT":
        present_value = evidence["value"]
        if value_kind == "decimal":
            require_decimal_string(present_value, f"{label}.value")
        elif value_kind == "integer":
            require_integer(present_value, f"{label}.value")
        elif value_kind == "positive_integer":
            require_integer(present_value, f"{label}.value", minimum=1)
        elif value_kind == "boolean":
            require_boolean(present_value, f"{label}.value")
        elif value_kind == "string":
            if not isinstance(present_value, str) or not present_value:
                raise RecorderContractError(f"{label}.value must be nonempty text.")
        elif value_kind == "identity":
            require_identity(present_value, f"{label}.value", kinds=identity_kinds)
    return evidence


def require_time_evidence(
    value: object,
    label: str,
    *,
    role: str | None = None,
) -> Mapping[str, object]:
    evidence = require_exact_fields(
        value,
        required={"role", "state", "authority", "reason_code"},
        optional={
            "raw_value",
            "normalized_rfc3339",
            "timezone_or_offset",
            "precision",
            "clock_uncertainty_ms",
            "normalization_rule_version",
            "source_record_id",
        },
        label=label,
    )
    state = _text(evidence, "state")
    if state not in AVAILABILITY_STATES:
        raise RecorderContractError(f"{label}.state is unsupported.")
    _text(evidence, "authority")
    _text(evidence, "reason_code")
    actual_role = _text(evidence, "role")
    if actual_role not in TIME_ROLES:
        raise RecorderContractError(f"{label}.role is unsupported.")
    if role is not None and actual_role != role:
        raise RecorderContractError(f"{label}.role must be {role}.")
    if state == "PRESENT":
        if evidence["reason_code"] != "PRESENT":
            raise RecorderContractError(f"{label} PRESENT requires PRESENT reason.")
        for field in (
            "raw_value",
            "normalized_rfc3339",
            "timezone_or_offset",
            "precision",
            "normalization_rule_version",
        ):
            _text(evidence, field)
        raw = str(evidence["raw_value"])
        normalized = str(evidence["normalized_rfc3339"])
        parse_rfc3339(normalized, f"{label}.normalized_rfc3339")
        if evidence["normalization_rule_version"] != TIME_NORMALIZATION_RULE or raw != normalized:
            raise RecorderContractError(
                f"{label} offline identity normalization requires exact raw==normalized."
            )
        offset = "Z" if normalized.endswith("Z") else normalized[-6:]
        if evidence["timezone_or_offset"] != offset:
            raise RecorderContractError(f"{label}.timezone_or_offset disagrees with timestamp suffix.")
        fraction = normalized.split("T", 1)[1].split("Z", 1)[0].split("+", 1)[0]
        if "-" in fraction[8:]:
            fraction = fraction.rsplit("-", 1)[0]
        expected_precision = (
            f"fractional-{len(fraction.rsplit('.', 1)[1])}"
            if "." in fraction
            else "second"
        )
        if evidence["precision"] != expected_precision:
            raise RecorderContractError(f"{label}.precision disagrees with timestamp bytes.")
    elif any(
        field in evidence
        for field in (
            "normalized_rfc3339",
            "raw_value",
            "timezone_or_offset",
            "precision",
            "normalization_rule_version",
        )
    ):
        raise RecorderContractError(f"{label} absent time cannot carry a timestamp.")
    if "clock_uncertainty_ms" in evidence:
        require_integer(evidence["clock_uncertainty_ms"], f"{label}.clock_uncertainty_ms")
    if "source_record_id" in evidence:
        source = evidence["source_record_id"]
        if isinstance(source, Mapping):
            require_identity(source, f"{label}.source_record_id")
        elif not isinstance(source, str) or not source:
            raise RecorderContractError(f"{label}.source_record_id must be an identity or text.")
    return evidence


def evidence_instant(value: object, label: str) -> object:
    evidence = require_time_evidence(value, label)
    if evidence["state"] != "PRESENT":
        raise RecorderContractError(f"{label} must be PRESENT for this relationship.")
    return parse_rfc3339(evidence["normalized_rfc3339"], label)


def require_instrument_identity(value: object, label: str) -> Mapping[str, object]:
    instrument = require_exact_fields(
        value,
        required={
            "instrument_identity_fingerprint_sha256",
            "symbol",
            "asset_type",
            "venue_or_exchange",
            "authoritative_security_id",
        },
        optional={"currency", "provider_security_ids"},
        label=label,
    )
    for field in ("symbol", "asset_type", "venue_or_exchange", "authoritative_security_id"):
        require_evidence_value(instrument[field], f"{label}.{field}", value_kind="string")
    if "currency" in instrument:
        require_evidence_value(instrument["currency"], f"{label}.currency", value_kind="string")
    if "provider_security_ids" in instrument:
        provider_ids = instrument["provider_security_ids"]
        if not isinstance(provider_ids, list):
            raise RecorderContractError(f"{label}.provider_security_ids must be an array.")
        for index, item in enumerate(provider_ids):
            provider_id = require_exact_fields(
                item,
                required={"owner_namespace", "owner_id"},
                optional={"owner_schema_version"},
                label=f"{label}.provider_security_ids[{index}]",
            )
            _text(provider_id, "owner_namespace")
            _text(provider_id, "owner_id")
            if "owner_schema_version" in provider_id:
                _text(provider_id, "owner_schema_version")
    supplied = require_sha256(
        instrument["instrument_identity_fingerprint_sha256"],
        f"{label}.instrument_identity_fingerprint_sha256",
    )
    material = dict(instrument)
    material.pop("instrument_identity_fingerprint_sha256")
    if sha256_hex(canonical_json_bytes(material)) != supplied:
        raise RecorderContractError(f"{label} fingerprint does not bind the full frozen identity.")
    return instrument


def _require_identity_array(
    value: object,
    label: str,
    *,
    kinds: frozenset[str] | None = None,
) -> list[object]:
    if not isinstance(value, list):
        raise RecorderContractError(f"{label} must be an array.")
    for index, item in enumerate(value):
        require_identity(item, f"{label}[{index}]", kinds=kinds)
    return value


def _require_reason_array(value: object, label: str, *, nonempty: bool = False) -> list[object]:
    if not isinstance(value, list) or (nonempty and not value):
        raise RecorderContractError(f"{label} must be {'a nonempty' if nonempty else 'an'} array.")
    for index, item in enumerate(value):
        require_versioned_reason(item, f"{label}[{index}]")
    return value


def _validate_discovery_profile(payload: Mapping[str, object]) -> None:
    require_exact_fields(
        payload,
        required={"discovery_cycle", "observations"},
        label="DISCOVERY_CYCLE payload",
    )
    cycle = require_exact_fields(
        payload["discovery_cycle"],
        required={
            "discovery_cycle_id",
            "cycle_state",
            "query_or_policy_fingerprint_sha256",
            "discovery_time",
            "provider_received_at",
            "returned_row_count",
            "row_order_complete",
            "observation_ids_in_source_order",
            "provider_health_event_ids",
            "zero_result",
            "completeness",
        },
        optional={
            "source_request_id",
            "source_cursor",
            "query_parameters_fingerprint_sha256",
            "source_total_count",
            "bounded_prefix_limit",
        },
        label="discovery_cycle",
    )
    require_identity(cycle["discovery_cycle_id"], "discovery_cycle_id", kinds=frozenset({"DISCOVERY_CYCLE_ID"}))
    if cycle["cycle_state"] not in {"COMPLETE", "ZERO_RESULT", "PARTIAL", "FAILED"}:
        raise RecorderContractError("discovery_cycle.cycle_state is unsupported.")
    require_sha256(cycle["query_or_policy_fingerprint_sha256"], "query_or_policy_fingerprint_sha256")
    require_time_evidence(cycle["discovery_time"], "discovery_time", role="DISCOVERY_TIME")
    require_time_evidence(cycle["provider_received_at"], "provider_received_at", role="PROVIDER_RECEIVED_AT")
    require_integer(cycle["returned_row_count"], "returned_row_count")
    require_evidence_value(cycle["row_order_complete"], "row_order_complete", value_kind="boolean")
    require_evidence_value(cycle["completeness"], "completeness", value_kind="string")
    require_boolean(cycle["zero_result"], "zero_result")
    _require_identity_array(cycle["observation_ids_in_source_order"], "observation_ids_in_source_order", kinds=frozenset({"OBSERVATION_ID"}))
    _require_identity_array(cycle["provider_health_event_ids"], "provider_health_event_ids", kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}))
    optional_evidence = {
        "source_request_id": "string",
        "source_cursor": "string",
        "query_parameters_fingerprint_sha256": "string",
        "source_total_count": "integer",
        "bounded_prefix_limit": "integer",
    }
    for field, kind in optional_evidence.items():
        if field in cycle:
            require_evidence_value(cycle[field], field, value_kind=kind)
            if field == "query_parameters_fingerprint_sha256" and cycle[field]["state"] == "PRESENT":
                require_sha256(cycle[field]["value"], f"{field}.value")
    rows = payload["observations"]
    if not isinstance(rows, list):
        raise RecorderContractError("observations must be an array.")
    candidate_fact_kinds = {
        "price": "decimal",
        "volume": "integer",
        "rvol": "decimal",
        "market_cap": "decimal",
        "float": "decimal",
        "gap_percent": "decimal",
        "persisted_score": "decimal",
        "score_version": "string",
    }
    for index, item in enumerate(rows):
        observation = require_exact_fields(
            item,
            required={
                "observation_id",
                "discovery_cycle_id",
                "source_row_ordinal",
                "source_row_fingerprint_sha256",
                "instrument_identity",
                "candidate_or_setup_identity",
                "rank",
                "discovery_time",
                "candidate_facts",
                "materially_evaluated",
                "rejection_or_gap_reasons",
            },
            optional={
                "market_snapshot_id",
                "catalyst_identities",
                "decision_ids",
                "owner_member_id",
            },
            label=f"observations[{index}]",
        )
        require_identity(observation["observation_id"], f"observations[{index}].observation_id", kinds=frozenset({"OBSERVATION_ID"}))
        require_identity(observation["discovery_cycle_id"], f"observations[{index}].discovery_cycle_id", kinds=frozenset({"DISCOVERY_CYCLE_ID"}))
        require_integer(observation["source_row_ordinal"], f"observations[{index}].source_row_ordinal")
        require_sha256(observation["source_row_fingerprint_sha256"], f"observations[{index}].source_row_fingerprint_sha256")
        require_instrument_identity(observation["instrument_identity"], f"observations[{index}].instrument_identity")
        require_identity(observation["candidate_or_setup_identity"], f"observations[{index}].candidate_or_setup_identity", kinds=frozenset({"CANDIDATE_MEMBER", "SETUP"}))
        require_evidence_value(observation["rank"], f"observations[{index}].rank", value_kind="positive_integer")
        require_time_evidence(observation["discovery_time"], f"observations[{index}].discovery_time", role="DISCOVERY_TIME")
        facts = require_exact_fields(
            observation["candidate_facts"],
            required=set(),
            optional=set(candidate_fact_kinds),
            label=f"observations[{index}].candidate_facts",
        )
        for field, fact in facts.items():
            require_evidence_value(fact, f"observations[{index}].candidate_facts.{field}", value_kind=candidate_fact_kinds[field])
        require_boolean(observation["materially_evaluated"], f"observations[{index}].materially_evaluated")
        _require_reason_array(observation["rejection_or_gap_reasons"], f"observations[{index}].rejection_or_gap_reasons")
        if "market_snapshot_id" in observation:
            require_evidence_value(observation["market_snapshot_id"], f"observations[{index}].market_snapshot_id", value_kind="identity", identity_kinds=frozenset({"MARKET_SNAPSHOT_ID"}))
        if "decision_ids" in observation:
            _require_identity_array(observation["decision_ids"], f"observations[{index}].decision_ids", kinds=frozenset({"DECISION_ID"}))
        if "owner_member_id" in observation:
            require_evidence_value(observation["owner_member_id"], f"observations[{index}].owner_member_id", value_kind="string")
        if "catalyst_identities" in observation:
            catalysts = observation["catalyst_identities"]
            if not isinstance(catalysts, list):
                raise RecorderContractError("catalyst_identities must be an array.")
            for catalyst_index, catalyst in enumerate(catalysts):
                item_label = f"observations[{index}].catalyst_identities[{catalyst_index}]"
                catalyst_value = require_exact_fields(
                    catalyst,
                    required={
                        "catalyst_id",
                        "source_owner",
                        "source_event_time",
                        "source_publication_time",
                        "provider_known_at",
                        "provider_received_at",
                    },
                    label=item_label,
                )
                require_identity(catalyst_value["catalyst_id"], f"{item_label}.catalyst_id")
                _text(catalyst_value, "source_owner")
                for field, role in (
                    ("source_event_time", "SOURCE_EVENT_TIME"),
                    ("source_publication_time", "SOURCE_PUBLICATION_TIME"),
                    ("provider_known_at", "PROVIDER_KNOWN_AT"),
                    ("provider_received_at", "PROVIDER_RECEIVED_AT"),
                ):
                    require_time_evidence(catalyst_value[field], f"{item_label}.{field}", role=role)


def validate_outcome_policy(value: object) -> Mapping[str, object]:
    required = {
        "policy_id",
        "policy_version",
        "policy_sha256",
        "frozen_before_session",
        "eligibility_mode",
        "horizons",
        "exchange_calendar_id_and_version",
        "bar_interval_semantic",
        "source_priority",
        "provider_owner_load_limit",
        "retry_and_finalization_cutoff",
        "outcome_selection_hindsight",
    }
    policy = require_exact_fields(
        value,
        required=required,
        optional={"policy_seed", "bucket_count_n", "selected_bucket_count_k"},
        label="outcome_followup_policy",
    )
    for field in ("policy_id", "policy_version", "exchange_calendar_id_and_version", "bar_interval_semantic"):
        _text(policy, field)
    if policy["frozen_before_session"] is not True:
        raise RecorderContractError("Outcome policy must be frozen before session.")
    if policy["eligibility_mode"] != "ALL_UNIQUE_INSTRUMENTS":
        raise RecorderContractError(
            "FIXED_HASH_BUCKET is not qualified by this bounded implementation."
        )
    if tuple(policy["horizons"]) != HORIZONS:
        raise RecorderContractError("Outcome policy must declare the exact P0 horizons.")
    if policy["outcome_selection_hindsight"] is not False:
        raise RecorderContractError("Outcome selection hindsight must be false.")
    if not isinstance(policy["source_priority"], list) or not policy["source_priority"] or not all(isinstance(item, str) and item for item in policy["source_priority"]):
        raise RecorderContractError("Outcome source priority must be a nonempty owner list.")
    require_evidence_value(policy["provider_owner_load_limit"], "provider_owner_load_limit", value_kind="integer")
    retry = require_exact_fields(
        policy["retry_and_finalization_cutoff"],
        required={"finalization_cutoff", "maximum_attempts"},
        label="retry_and_finalization_cutoff",
    )
    parse_rfc3339(retry["finalization_cutoff"], "retry_and_finalization_cutoff.finalization_cutoff")
    require_integer(retry["maximum_attempts"], "retry_and_finalization_cutoff.maximum_attempts", minimum=1)
    supplied = require_sha256(policy["policy_sha256"], "policy_sha256")
    material = dict(policy)
    material.pop("policy_sha256")
    if sha256_hex(canonical_json_bytes(material)) != supplied:
        raise RecorderContractError("Outcome policy SHA-256 does not match its frozen bytes.")
    return policy


def validate_start_manifest(
    payload: Mapping[str, object],
    *,
    session_id: Mapping[str, object],
    source_root_identity: str,
) -> None:
    require_exact_fields(
        payload,
        required={
            "exchange_market_date",
            "manifest_phase",
            "market_timezone",
            "outcome_followup_policy",
            "regular_session_close",
            "regular_session_open",
            "session_id",
            "session_kind",
            "source_owner_namespace",
            "source_root_identity",
            "source_runtime_activation_id",
        },
        label="START manifest",
    )
    if payload.get("manifest_phase") != "START":
        raise RecorderContractError("The first session manifest must have START phase.")
    if payload.get("source_root_identity") != source_root_identity:
        raise RecorderContractError("Source root identity does not match configured custody.")
    require_identity(payload.get("session_id"), "payload.session_id", kinds=frozenset({"SESSION_ID"}))
    if dict(payload["session_id"]) != dict(session_id):
        raise RecorderContractError("Envelope and manifest session identities differ.")
    market_date = _text(payload, "exchange_market_date")
    try:
        date.fromisoformat(market_date)
    except ValueError as exc:
        raise RecorderContractError("exchange_market_date must be ISO calendar date.") from exc
    for field in (
        "session_kind",
        "market_timezone",
        "regular_session_open",
        "regular_session_close",
        "source_owner_namespace",
        "source_runtime_activation_id",
    ):
        _text(payload, field)
    parse_rfc3339(payload["regular_session_open"], "regular_session_open")
    parse_rfc3339(payload["regular_session_close"], "regular_session_close")
    if parse_rfc3339(payload["regular_session_open"], "regular_session_open") >= parse_rfc3339(
        payload["regular_session_close"], "regular_session_close"
    ):
        raise RecorderContractError("Regular session open must precede close.")
    validate_outcome_policy(_required(payload, "outcome_followup_policy"))


def validate_final_manifest_profile(payload: Mapping[str, object]) -> None:
    final = require_exact_fields(
        payload,
        required={
            "close_reason",
            "closed_at",
            "conflict_count",
            "manifest_phase",
            "pending_source_events",
            "session_id",
            "source_event_type_counts_before_final",
            "source_gap_count",
            "source_root_identity",
            "source_stream_heads_before_final",
        },
        label="source FINAL manifest",
    )
    if final["manifest_phase"] != "FINAL":
        raise RecorderContractError("Source FINAL manifest_phase must be FINAL.")
    _text(final, "close_reason")
    parse_rfc3339(final["closed_at"], "closed_at")
    require_identity(final["session_id"], "session_id", kinds=frozenset({"SESSION_ID"}))
    require_sha256(final["source_root_identity"], "source_root_identity")
    for field in ("conflict_count", "pending_source_events", "source_gap_count"):
        require_integer(final[field], field)
    counts = require_exact_fields(
        final["source_event_type_counts_before_final"],
        required=set(EVENT_TYPES),
        label="source_event_type_counts_before_final",
    )
    for event_type, count in counts.items():
        require_integer(count, f"source_event_type_counts_before_final.{event_type}")
    heads = final["source_stream_heads_before_final"]
    if not isinstance(heads, list):
        raise RecorderContractError("source_stream_heads_before_final must be an array.")
    seen: set[str] = set()
    for index, item in enumerate(heads):
        head = require_exact_fields(
            item,
            required={"stream_id", "last_source_sequence", "last_source_envelope_sha256"},
            label=f"source_stream_heads_before_final[{index}]",
        )
        stream_id = _text(head, "stream_id")
        if stream_id in seen:
            raise RecorderContractError("Source FINAL repeats a stream head.")
        seen.add(stream_id)
        require_integer(head["last_source_sequence"], f"source_stream_heads_before_final[{index}].last_source_sequence", minimum=1)
        require_sha256(head["last_source_envelope_sha256"], f"source_stream_heads_before_final[{index}].last_source_envelope_sha256")


def _validate_reference_level_profile(value: object, label: str, role: str) -> None:
    level = require_exact_fields(
        value,
        required={"state", "reason_code", "level_role", "authority"},
        optional={
            "reference_level_id",
            "value",
            "currency",
            "level_source_fingerprint_sha256",
        },
        label=label,
    )
    state = _text(level, "state")
    if state not in AVAILABILITY_STATES or level.get("level_role") != role:
        raise RecorderContractError(f"{label} has invalid state or role.")
    _text(level, "authority")
    reason = _text(level, "reason_code")
    conditional = {
        "reference_level_id",
        "value",
        "currency",
        "level_source_fingerprint_sha256",
    }
    if state == "PRESENT":
        if not conditional.issubset(level) or reason != "PRESENT":
            raise RecorderContractError(f"{label} PRESENT fields are incomplete.")
        require_identity(level["reference_level_id"], f"{label}.reference_level_id", kinds=frozenset({"REFERENCE_LEVEL_ID"}))
        require_decimal_string(level["value"], f"{label}.value")
        _text(level, "currency")
        require_sha256(level["level_source_fingerprint_sha256"], f"{label}.level_source_fingerprint_sha256")
    elif conditional.intersection(level):
        raise RecorderContractError(f"{label} non-PRESENT state prohibits level value fields.")


def _validate_decision_profile(payload: Mapping[str, object]) -> None:
    require_exact_fields(
        payload,
        required={"decision_event"},
        optional={"reference_plan"},
        label="DECISION_FACT payload",
    )
    decision = require_exact_fields(
        payload["decision_event"],
        required={
            "decision_id",
            "observation_id",
            "candidate_or_setup_identity",
            "decision_state",
            "reason_codes",
            "decision_time",
            "decision_cutoff",
            "known_at_evidence_refs",
            "strategy_identity",
            "decision_policy_fingerprint_sha256",
            "config_fingerprint_sha256",
            "runtime_fingerprint_sha256",
            "outcome_eligibility_commitment_sha256",
            "market_snapshot_id",
            "tradeplan_id",
            "reference_plan_id",
        },
        optional={
            "score",
            "score_version",
            "catalyst_refs",
            "provider_health_event_ids",
            "supersedes_decision_id",
        },
        label="decision_event",
    )
    require_identity(decision["decision_id"], "decision_id", kinds=frozenset({"DECISION_ID"}))
    require_identity(decision["observation_id"], "observation_id", kinds=frozenset({"OBSERVATION_ID"}))
    require_identity(decision["candidate_or_setup_identity"], "candidate_or_setup_identity", kinds=frozenset({"CANDIDATE_MEMBER", "SETUP"}))
    if decision["decision_state"] not in {"READY", "BLOCKED", "REJECTED", "MISSED", "NO_PLAN", "TRADEPLAN"}:
        raise RecorderContractError("decision_state is unsupported.")
    _require_reason_array(decision["reason_codes"], "reason_codes", nonempty=True)
    require_time_evidence(decision["decision_time"], "decision_time", role="DECISION_TIME")
    require_time_evidence(decision["decision_cutoff"], "decision_cutoff", role="DECISION_CUTOFF")
    refs = decision["known_at_evidence_refs"]
    if not isinstance(refs, list):
        raise RecorderContractError("known_at_evidence_refs must be an array.")
    for index, ref in enumerate(refs):
        known_ref = require_exact_fields(
            ref,
            required={"record_id", "evidence_field_path", "known_at", "payload_sha256"},
            label=f"known_at_evidence_refs[{index}]",
        )
        require_identity(known_ref["record_id"], f"known_at_evidence_refs[{index}].record_id")
        path = _text(known_ref, "evidence_field_path")
        if not path.startswith("/") or path == "/":
            raise RecorderContractError("evidence_field_path must be a non-root JSON Pointer.")
        known = require_time_evidence(known_ref["known_at"], f"known_at_evidence_refs[{index}].known_at")
        if known["role"] not in {"PROVIDER_KNOWN_AT", "PROVIDER_RECEIVED_AT"}:
            raise RecorderContractError("Known-at reference must use a provider-known/received role.")
        require_sha256(known_ref["payload_sha256"], f"known_at_evidence_refs[{index}].payload_sha256")
    require_evidence_value(decision["strategy_identity"], "strategy_identity", value_kind="string")
    for field in (
        "decision_policy_fingerprint_sha256",
        "config_fingerprint_sha256",
        "runtime_fingerprint_sha256",
        "outcome_eligibility_commitment_sha256",
    ):
        require_sha256(decision[field], field)
    require_evidence_value(decision["market_snapshot_id"], "market_snapshot_id", value_kind="identity", identity_kinds=frozenset({"MARKET_SNAPSHOT_ID"}))
    require_evidence_value(decision["tradeplan_id"], "tradeplan_id", value_kind="identity", identity_kinds=frozenset({"TRADEPLAN_ID"}))
    require_evidence_value(decision["reference_plan_id"], "reference_plan_id", value_kind="identity", identity_kinds=frozenset({"REFERENCE_PLAN_ID"}))
    if "score" in decision:
        require_evidence_value(decision["score"], "score", value_kind="decimal")
    if "score_version" in decision:
        require_evidence_value(decision["score_version"], "score_version", value_kind="string")
    if "provider_health_event_ids" in decision:
        _require_identity_array(decision["provider_health_event_ids"], "provider_health_event_ids", kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}))
    if "supersedes_decision_id" in decision:
        require_evidence_value(decision["supersedes_decision_id"], "supersedes_decision_id", value_kind="identity", identity_kinds=frozenset({"DECISION_ID"}))
    if "catalyst_refs" in decision:
        if not isinstance(decision["catalyst_refs"], list):
            raise RecorderContractError("catalyst_refs must be an array.")
        for index, ref in enumerate(decision["catalyst_refs"]):
            catalyst_ref = require_exact_fields(
                ref,
                required={"record_id", "payload_sha256", "evidence_field_path", "known_at"},
                label=f"catalyst_refs[{index}]",
            )
            require_identity(catalyst_ref["record_id"], f"catalyst_refs[{index}].record_id")
            require_sha256(catalyst_ref["payload_sha256"], f"catalyst_refs[{index}].payload_sha256")
            _text(catalyst_ref, "evidence_field_path")
            require_time_evidence(catalyst_ref["known_at"], f"catalyst_refs[{index}].known_at")
    if "reference_plan" not in payload:
        return
    plan = require_exact_fields(
        payload["reference_plan"],
        required={
            "reference_plan_id",
            "tradeplan_id",
            "decision_id",
            "candidate_or_setup_identity",
            "plan_owner",
            "plan_schema_version",
            "plan_source_fingerprint_sha256",
            "plan_created_at",
            "entry",
            "stop",
            "t1",
            "t2",
        },
        optional={"supersedes_reference_plan_id"},
        label="reference_plan",
    )
    require_identity(plan["reference_plan_id"], "reference_plan_id", kinds=frozenset({"REFERENCE_PLAN_ID"}))
    require_identity(plan["tradeplan_id"], "tradeplan_id", kinds=frozenset({"TRADEPLAN_ID"}))
    require_identity(plan["decision_id"], "decision_id", kinds=frozenset({"DECISION_ID"}))
    require_identity(plan["candidate_or_setup_identity"], "candidate_or_setup_identity", kinds=frozenset({"SETUP"}))
    _text(plan, "plan_owner")
    _text(plan, "plan_schema_version")
    require_sha256(plan["plan_source_fingerprint_sha256"], "plan_source_fingerprint_sha256")
    require_time_evidence(plan["plan_created_at"], "plan_created_at")
    for field, role in (("entry", "ENTRY"), ("stop", "STOP"), ("t1", "T1"), ("t2", "T2")):
        _validate_reference_level_profile(plan[field], field, role)
    if "supersedes_reference_plan_id" in plan:
        require_evidence_value(plan["supersedes_reference_plan_id"], "supersedes_reference_plan_id", value_kind="identity", identity_kinds=frozenset({"REFERENCE_PLAN_ID"}))


def _validate_market_profile(payload: Mapping[str, object]) -> None:
    require_exact_fields(payload, required={"market_snapshot"}, label="MARKET_FACT payload")
    record = require_exact_fields(
        payload["market_snapshot"],
        required={
            "market_snapshot_id",
            "snapshot_kind",
            "instrument_identity",
            "observation_id",
            "decision_id",
            "outcome_series_id",
            "source_event_time",
            "provider_known_at",
            "provider_received_at",
            "market_facts",
            "market_data_owner",
            "source_market_fact_fingerprint_sha256",
        },
        optional={"provider_health_event_ids", "raw_source_field_fingerprint_sha256"},
        label="market_snapshot",
    )
    require_identity(record["market_snapshot_id"], "market_snapshot_id", kinds=frozenset({"MARKET_SNAPSHOT_ID"}))
    require_instrument_identity(record["instrument_identity"], "instrument_identity")
    require_evidence_value(record["observation_id"], "observation_id", value_kind="identity", identity_kinds=frozenset({"OBSERVATION_ID"}))
    require_evidence_value(record["decision_id"], "decision_id", value_kind="identity", identity_kinds=frozenset({"DECISION_ID"}))
    require_evidence_value(record["outcome_series_id"], "outcome_series_id", value_kind="identity", identity_kinds=frozenset({"OUTCOME_SERIES_ID"}))
    require_time_evidence(record["source_event_time"], "source_event_time", role="SOURCE_EVENT_TIME")
    require_time_evidence(record["provider_known_at"], "provider_known_at", role="PROVIDER_KNOWN_AT")
    require_time_evidence(record["provider_received_at"], "provider_received_at", role="PROVIDER_RECEIVED_AT")
    market_fact_kinds = {
        "price": "decimal", "bid": "decimal", "ask": "decimal", "mark": "decimal",
        "spread": "decimal", "volume": "integer", "rvol": "decimal",
        "market_cap": "decimal", "persisted_score": "decimal", "score_version": "string",
        "bar_open": "decimal", "bar_high": "decimal", "bar_low": "decimal",
        "bar_close": "decimal", "bar_volume": "integer", "bar_complete": "boolean",
    }
    facts = require_exact_fields(
        record["market_facts"],
        required=set(),
        optional=set(market_fact_kinds).union({"bar_interval_start", "bar_interval_end"}),
        label="market_facts",
    )
    for field, fact in facts.items():
        if field in {"bar_interval_start", "bar_interval_end"}:
            require_time_evidence(fact, f"market_facts.{field}")
        else:
            require_evidence_value(fact, f"market_facts.{field}", value_kind=market_fact_kinds[field])
    _text(record, "market_data_owner")
    require_sha256(record["source_market_fact_fingerprint_sha256"], "source_market_fact_fingerprint_sha256")
    if "provider_health_event_ids" in record:
        _require_identity_array(record["provider_health_event_ids"], "provider_health_event_ids", kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}))
    if "raw_source_field_fingerprint_sha256" in record:
        evidence = require_evidence_value(record["raw_source_field_fingerprint_sha256"], "raw_source_field_fingerprint_sha256", value_kind="string")
        if evidence["state"] == "PRESENT":
            require_sha256(evidence["value"], "raw_source_field_fingerprint_sha256.value")


def _validate_health_profile(payload: Mapping[str, object]) -> None:
    require_exact_fields(payload, required={"provider_health_event"}, label="PROVIDER_HEALTH payload")
    record = require_exact_fields(
        payload["provider_health_event"],
        required={
            "provider_health_event_id", "interface_or_owner", "event_class", "event_state",
            "reason_code", "source_event_time", "provider_received_at", "affected_record_ids",
            "attempt_number", "terminal", "secret_material_present",
        },
        optional={
            "request_fingerprint_sha256", "http_status", "provider_error_class",
            "auth_refresh_result", "recovery_event_id", "source_cursor",
        },
        label="provider_health_event",
    )
    require_identity(record["provider_health_event_id"], "provider_health_event_id", kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}))
    _text(record, "interface_or_owner")
    if record["event_class"] not in {
        "UNAVAILABLE", "STALE", "PARTIAL", "AUTH_REFRESH", "HTTP_FAILURE",
        "MISSING_CANDLE", "MISSING_QUOTE", "READINESS_FAILURE", "CAPACITY_EXCLUSION",
        "SOURCE_OUTAGE", "SOURCE_RETENTION_GAP", "CLOCK_CONFLICT", "SCHEMA_CONFLICT",
    }:
        raise RecorderContractError("provider_health_event.event_class is unsupported.")
    if record["event_state"] not in AVAILABILITY_STATES:
        raise RecorderContractError("provider_health_event.event_state is unsupported.")
    _text(record, "reason_code")
    require_time_evidence(record["source_event_time"], "source_event_time", role="SOURCE_EVENT_TIME")
    require_time_evidence(record["provider_received_at"], "provider_received_at", role="PROVIDER_RECEIVED_AT")
    _require_identity_array(record["affected_record_ids"], "affected_record_ids")
    require_evidence_value(record["attempt_number"], "attempt_number", value_kind="integer")
    require_boolean(record["terminal"], "terminal")
    if record["secret_material_present"] is not False:
        raise RecorderContractError("secret_material_present must be false.")
    optional_kinds = {
        "request_fingerprint_sha256": "string", "http_status": "integer",
        "provider_error_class": "string", "auth_refresh_result": "string",
        "recovery_event_id": "identity", "source_cursor": "string",
    }
    for field, kind in optional_kinds.items():
        if field in record:
            require_evidence_value(
                record[field], field, value_kind=kind,
                identity_kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}) if field == "recovery_event_id" else None,
            )
            if field == "request_fingerprint_sha256" and record[field]["state"] == "PRESENT":
                require_sha256(record[field]["value"], f"{field}.value")


def validate_export_payload_profile(event_type: str, payload: Mapping[str, object]) -> None:
    if event_type == "DISCOVERY_CYCLE":
        _validate_discovery_profile(payload)
    elif event_type == "DECISION_FACT":
        _validate_decision_profile(payload)
    elif event_type == "MARKET_FACT":
        _validate_market_profile(payload)
    elif event_type == "PROVIDER_HEALTH":
        _validate_health_profile(payload)
    elif event_type == "SESSION_MANIFEST":
        if payload.get("manifest_phase") == "START":
            validate_outcome_policy(_required(payload, "outcome_followup_policy"))
        elif payload.get("manifest_phase") == "FINAL":
            validate_final_manifest_profile(payload)
        else:
            raise RecorderContractError("Session manifest phase must be START or FINAL.")
    else:
        raise RecorderContractError("Unsupported export event type.")


def validate_export_clock_relationships(
    envelope: Mapping[str, object],
    event_type: str,
    payload: Mapping[str, object],
) -> None:
    event_time = parse_rfc3339(envelope["event_time"], "event_time")
    effective = parse_rfc3339(envelope["effective_known_at"], "effective_known_at")
    emitted = parse_rfc3339(envelope["emitted_at"], "emitted_at")
    if event_time > emitted or effective > emitted:
        raise RecorderContractError("Envelope event/effective clocks cannot follow emitted_at.")
    if event_type == "DISCOVERY_CYCLE":
        cycle = payload["discovery_cycle"]
        authoritative_event = evidence_instant(cycle["discovery_time"], "discovery_time")
        authoritative_effective = evidence_instant(cycle["provider_received_at"], "provider_received_at")
    elif event_type == "DECISION_FACT":
        decision = payload["decision_event"]
        authoritative_event = evidence_instant(decision["decision_time"], "decision_time")
        authoritative_effective = evidence_instant(decision["decision_cutoff"], "decision_cutoff")
    elif event_type == "MARKET_FACT":
        market = payload["market_snapshot"]
        authoritative_event = evidence_instant(market["source_event_time"], "source_event_time")
        known = market["provider_known_at"]
        authoritative_effective = evidence_instant(
            known if known.get("state") == "PRESENT" else market["provider_received_at"],
            "market effective known-at",
        )
        received = market["provider_received_at"]
        if received.get("state") == "PRESENT" and evidence_instant(received, "provider_received_at") > emitted:
            raise RecorderContractError("Market provider receipt cannot follow emitted_at.")
    elif event_type == "PROVIDER_HEALTH":
        health = payload["provider_health_event"]
        authoritative_event = evidence_instant(health["source_event_time"], "source_event_time")
        authoritative_effective = evidence_instant(health["provider_received_at"], "provider_received_at")
    elif payload.get("manifest_phase") == "FINAL":
        authoritative_event = parse_rfc3339(payload["closed_at"], "closed_at")
        authoritative_effective = authoritative_event
    else:
        authoritative_event = event_time
        authoritative_effective = effective
    if event_time != authoritative_event or effective != authoritative_effective:
        raise RecorderContractError("Envelope clocks disagree with phase/event semantic clocks.")


def parse_export_envelope(raw: bytes) -> ValidatedExportEnvelope:
    try:
        value = strict_json_loads(raw)
    except CanonicalizationError as exc:
        raise RecorderContractError(str(exc)) from exc
    required_fields = {
        "schema_version",
        "offline_reference_profile",
        "canonicalization_version",
        "hash_algorithm",
        "hash_unit",
        "previous_record_hash_target",
        "source_sequence_scope",
        "event_type",
        "stream_id",
        "session_id",
        "source_owner_identity",
        "source_interface_identity",
        "source_contract",
        "source_contract_version",
        "source_event_id",
        "source_event_fingerprint_sha256",
        "source_sequence",
        "event_time",
        "effective_known_at",
        "emitted_at",
        "previous_record_sha256",
        "payload_sha256",
        "authority",
        "execution_authority",
        "payload",
    }
    if set(value) != required_fields:
        raise RecorderContractError("Export envelope has missing or unknown top-level fields.")
    if value["schema_version"] != SCHEMA_VERSION:
        raise RecorderContractError("Unsupported export schema version; fail closed.")
    from .canonical import CANONICALIZATION_VERSION

    exact_profile = {
        "offline_reference_profile": SCIENCE_OFFLINE_EXPORT_PROFILE,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "hash_unit": HASH_UNIT,
        "previous_record_hash_target": PREVIOUS_HASH_TARGET,
        "source_sequence_scope": SOURCE_SEQUENCE_SCOPE,
    }
    for field, expected in exact_profile.items():
        if value[field] != expected:
            raise RecorderContractError(f"Unsupported offline reference profile field: {field}.")
    event_type = _text(value, "event_type")
    if event_type not in EVENT_TYPES:
        raise RecorderContractError("Unsupported export event type.")
    if (
        value["source_contract"] != SOURCE_CONTRACT
        or value["source_contract_version"] != PREDECESSOR_SCHEMA_VERSION
    ):
        raise RecorderContractError("Unsupported source contract lineage.")
    if value["authority"] != AUTHORITY or value["execution_authority"] != EXECUTION_AUTHORITY:
        raise RecorderContractError("Envelope attempts to exceed research-only authority.")
    session_id = require_identity(
        value["session_id"], "session_id", kinds=frozenset({"SESSION_ID"})
    )
    sequence = value["source_sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise RecorderContractError("source_sequence must be a positive integer.")
    for field in ("event_time", "effective_known_at", "emitted_at"):
        parse_rfc3339(value[field], field)
    previous = value["previous_record_sha256"]
    if previous != GENESIS_SHA256:
        require_sha256(previous, "previous_record_sha256")
    require_sha256(value["source_event_fingerprint_sha256"], "source_event_fingerprint_sha256")
    payload_sha = require_sha256(value["payload_sha256"], "payload_sha256")
    payload = value["payload"]
    if not isinstance(payload, Mapping):
        raise RecorderContractError("payload must be an object.")
    if sha256_hex(canonical_json_bytes(payload)) != payload_sha:
        raise RecorderContractError("payload_sha256 does not match canonical payload bytes.")
    _walk_prohibited(value)
    validate_export_payload_profile(event_type, payload)
    validate_export_clock_relationships(value, event_type, payload)
    return ValidatedExportEnvelope(
        raw_bytes=raw,
        raw_sha256=sha256_hex(raw),
        schema_version=SCHEMA_VERSION,
        event_type=event_type,
        stream_id=_text(value, "stream_id"),
        session_id=session_id,
        source_owner_identity=_text(value, "source_owner_identity"),
        source_interface_identity=_text(value, "source_interface_identity"),
        source_contract=SOURCE_CONTRACT,
        source_contract_version=PREDECESSOR_SCHEMA_VERSION,
        source_event_id=_text(value, "source_event_id"),
        source_event_fingerprint_sha256=str(value["source_event_fingerprint_sha256"]),
        source_sequence=sequence,
        event_time=str(value["event_time"]),
        effective_known_at=str(value["effective_known_at"]),
        emitted_at=str(value["emitted_at"]),
        previous_record_sha256=str(previous),
        payload_sha256=payload_sha,
        payload=payload,
    )


# Public handoff name.  This remains an offline Science reference parser, not
# an operative cross-lane DTO implementation.
parse_export_envelope_v1 = parse_export_envelope


__all__ = [
    "AUTHORITY",
    "AVAILABILITY_STATES",
    "BASE_CANONICAL_SHA",
    "EVENT_CHANNEL",
    "EVENT_TYPES",
    "EXECUTION_AUTHORITY",
    "GENESIS_SHA256",
    "HASH_ALGORITHM",
    "HASH_UNIT",
    "HORIZONS",
    "PROVIDER_DERIVED_TERMINAL_OUTCOME_STATES",
    "PREDECESSOR_DIRECTIVE",
    "PREDECESSOR_SCHEMA_VERSION",
    "PREDECESSOR_SCHEMA_SHA256",
    "PREDECESSOR_SIDECAR_SHA256",
    "RECORD_FAMILIES",
    "RecorderContractError",
    "SCHEMA_MAJOR_VERSION",
    "SCHEMA_VERSION",
    "SCIENCE_OFFLINE_EXPORT_PROFILE",
    "SOURCE_CONTRACT",
    "SOURCE_SEQUENCE_SCOPE",
    "TERMINAL_OUTCOME_STATES",
    "PREVIOUS_HASH_TARGET",
    "ValidatedExportEnvelope",
    "evidence_instant",
    "parse_export_envelope",
    "parse_export_envelope_v1",
    "require_evidence_value",
    "require_exact_fields",
    "require_instrument_identity",
    "require_integer",
    "require_boolean",
    "require_decimal_string",
    "require_identity",
    "reject_prohibited_fields",
    "require_time_evidence",
    "require_versioned_reason",
    "TIME_NORMALIZATION_RULE",
    "TIME_ROLES",
    "validate_export_clock_relationships",
    "validate_export_payload_profile",
    "validate_final_manifest_profile",
    "validate_outcome_policy",
    "validate_start_manifest",
]
