"""Versioned, one-way producer fact export for future Science custody.

The contract is intentionally dormant.  It accepts caller-supplied facts and
writes only to an explicit, isolated export root after ``initialize`` is
called.  It has no provider, account, broker, order, scheduler, service,
strategy, UI, Paper, Shadow, callback, or execution capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "ARGUS_RESEARCH_EXPORT_V1"
CANONICALIZATION_VERSION = "ARGUS_CANONICAL_JSON_V1"
RECEIPT_VERSION = "ARGUS_RESEARCH_EXPORT_RECEIPT_V1"
CHECKPOINT_VERSION = "ARGUS_RESEARCH_EXPORT_CHECKPOINT_V1"
IDENTITY_NAMESPACE = "argus-science-recorder-v1"
AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
ZERO_SHA256 = "0" * 64

EVENT_TYPES = frozenset(
    {
        "DISCOVERY_CYCLE",
        "DECISION_FACT",
        "MARKET_FACT",
        "PROVIDER_HEALTH",
        "SESSION_MANIFEST",
    }
)
RECORD_CHANNELS = {
    "discovery-cycle": "discovery",
    "candidate-observation": "discovery",
    "decision-event": "decision",
    "reference-plan": "decision",
    "market-snapshot": "market",
    "provider-health-event": "health",
    "outcome-observation": "outcome",
}
EVENT_RECORD_TYPES = {
    "DISCOVERY_CYCLE": frozenset({"discovery-cycle", "candidate-observation"}),
    "DECISION_FACT": frozenset({"decision-event", "reference-plan"}),
    "MARKET_FACT": frozenset({"market-snapshot", "outcome-observation"}),
    "PROVIDER_HEALTH": frozenset({"provider-health-event"}),
    "SESSION_MANIFEST": frozenset(),
}
EVENT_CHANNELS = {
    "DISCOVERY_CYCLE": "discovery",
    "DECISION_FACT": "decision",
    "MARKET_FACT": "market",
    "PROVIDER_HEALTH": "health",
    "SESSION_MANIFEST": "session",
}
CHANNELS = ("session", "discovery", "decision", "market", "health", "outcome")

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
IDENTITY_TYPES = frozenset(
    {
        "SESSION",
        "DISCOVERY_CYCLE",
        "OBSERVATION",
        "CANDIDATE_MEMBER",
        "SETUP",
        "DECISION",
        "TRADEPLAN",
        "REFERENCE_PLAN",
        "REFERENCE_LEVEL",
        "MARKET_SNAPSHOT",
        "PROVIDER_HEALTH_EVENT",
        "OUTCOME_SERIES",
        "OUTCOME_OBSERVATION",
    }
)
OUTCOME_HORIZONS = (
    "PLUS_5M",
    "PLUS_15M",
    "PLUS_30M",
    "PLUS_60M",
    "SESSION_CLOSE",
    "MFE",
    "MAE",
)
COVERAGE_METRIC_IDS = (
    "DISCOVERY_CYCLE_COVERAGE",
    "DENOMINATOR_ROW_COVERAGE",
    "DECISION_IDENTITY_COVERAGE",
    "QUOTE_SNAPSHOT_COVERAGE",
    "SCORE_COVERAGE",
    "CATALYST_IDENTITY_COVERAGE",
    "REFERENCE_LEVEL_COVERAGE",
    "OUTCOME_ELIGIBILITY_ACCOUNTING_COVERAGE",
    "OUTCOME_ATTEMPT_OR_GAP_RECEIPT_COVERAGE",
    "OUTCOME_ELIGIBLE_SYMBOL_COVERAGE",
    "OUTCOME_ELIGIBLE_DECISION_COVERAGE",
    "OUTCOME_HORIZON_COVERAGE",
    "KNOWN_AT_COVERAGE",
    "RESTART_RECOVERY_SUCCESS",
    "RECEIPT_CHAIN_VERIFICATION",
    "RECORDER_LAG",
)
CANDIDATE_FACT_FIELDS = frozenset(
    {
        "price",
        "volume",
        "rvol",
        "market_cap",
        "float",
        "gap_percent",
        "persisted_score",
        "score_version",
    }
)
MARKET_FACT_FIELDS = frozenset(
    {
        "price",
        "bid",
        "ask",
        "mark",
        "spread",
        "volume",
        "rvol",
        "market_cap",
        "persisted_score",
        "score_version",
        "bar_open",
        "bar_high",
        "bar_low",
        "bar_close",
        "bar_volume",
        "bar_interval_start",
        "bar_interval_end",
        "bar_complete",
    }
)

COMMON_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "record_id",
        "session_id",
        "partition_id",
        "record_sequence",
        "source_owner",
        "source_record_identity",
        "source_fingerprint_sha256",
        "recorder_capture_time",
        "availability",
        "producer_export_envelope_id",
    }
)
REQUIRED_RECORD_FIELDS = {
    "discovery-cycle": frozenset(
        {
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
        }
    ),
    "candidate-observation": frozenset(
        {
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
            "outcome_eligibility",
        }
    ),
    "decision-event": frozenset(
        {
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
        }
    ),
    "market-snapshot": frozenset(
        {
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
        }
    ),
    "reference-plan": frozenset(
        {
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
        }
    ),
    "provider-health-event": frozenset(
        {
            "provider_health_event_id",
            "interface_or_owner",
            "event_class",
            "event_state",
            "reason_code",
            "source_event_time",
            "provider_received_at",
            "affected_record_ids",
            "attempt_number",
            "terminal",
            "secret_material_present",
        }
    ),
    "outcome-observation": frozenset(
        {
            "outcome_observation_id",
            "outcome_series_id",
            "decision_id",
            "decision_payload_sha256",
            "observation_id",
            "candidate_or_setup_identity",
            "eligibility_commitment_sha256",
            "outcome_semantic",
            "outcome_semantic_version",
            "target_time",
            "outcome_time",
            "outcome_value",
            "outcome_state",
            "canonical_path_fingerprint_sha256",
            "canonical_bar_record_ids",
            "path_completeness",
            "transform_version",
            "linkage_receipt_sha256",
        }
    ),
}

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MARKET_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_RECORD_TYPE = re.compile(r"[a-z][a-z0-9-]{0,63}")
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "account",
        "account_id",
        "account_number",
        "broker",
        "broker_id",
        "callback",
        "command",
        "order",
        "order_id",
        "order_payload",
        "position",
        "positions",
        "paper",
        "shadow",
        "execution",
        "execution_request",
        "execution_result",
        "api_key",
        "access_token",
        "refresh_token",
        "credential",
        "credentials",
        "secret",
    }
)


class ResearchFactExportError(RuntimeError):
    """Raised when the one-way research export contract cannot be proven."""


class ResearchFactConflict(ResearchFactExportError):
    """Raised after a same-identity/different-bytes conflict is persisted."""


class QualificationInterruption(ResearchFactExportError):
    """Fault-injection interruption used only by offline qualification tests."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return strict ARGUS_CANONICAL_JSON_V1 bytes, including one LF."""

    _validate_canonical_value(value)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def recorder_identity(identity_type: str, logical_key: Mapping[str, Any]) -> dict[str, Any]:
    """Allocate a stable logical identity without using payload bytes."""

    kind = _identity_kind(identity_type)
    if not isinstance(logical_key, Mapping) or not logical_key:
        raise ResearchFactExportError("Identity logical_key must be a nonempty object")
    normalized_key = dict(logical_key)
    normalized_names = {str(key).lower() for key in normalized_key}
    if normalized_names <= {"symbol", "ticker"}:
        raise ResearchFactExportError("Symbol alone is not a lifecycle logical key")
    material = {
        "identity_type": kind,
        "logical_key": normalized_key,
        "namespace": IDENTITY_NAMESPACE,
    }
    logical_hash = fingerprint(material)
    return {
        "allocation_mode": "RECORDER_DURABLE_ALLOCATED",
        "identity_kind": kind,
        "logical_key_fingerprint_sha256": logical_hash,
        "recorder_id": f"ar1:{kind.lower()}:{logical_hash}",
    }


def owner_identity(
    identity_type: str,
    owner_namespace: str,
    owner_id: str,
    *,
    owner_schema_version: str = "1",
) -> dict[str, Any]:
    """Wrap, but never replace or reinterpret, an owner-issued identity."""

    kind = _identity_kind(identity_type)
    namespace = _required_text(owner_namespace, "Owner namespace")
    exact_owner_id = _required_text(owner_id, "Owner ID")
    version = _required_text(owner_schema_version, "Owner schema version")
    material = {
        "identity_type": kind,
        "logical_key": {
            "owner_id": exact_owner_id,
            "owner_namespace": namespace,
            "owner_schema_version": version,
        },
        "namespace": IDENTITY_NAMESPACE,
    }
    return {
        "allocation_mode": "OWNER_WRAPPED",
        "identity_kind": kind,
        "owner_id": exact_owner_id,
        "owner_namespace": namespace,
        "owner_schema_version": version,
        "recorder_id": f"ar1:{kind.lower()}:{fingerprint(material)}",
    }


def evidence_present(
    value: Any,
    authority: str,
    *,
    source_record_id: str | None = None,
    source_fingerprint_sha256: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "authority": _required_text(authority, "Evidence authority"),
        "reason_code": "PRESENT",
        "state": "PRESENT",
        "value": value,
    }
    if source_record_id is not None:
        result["source_record_id"] = _required_text(source_record_id, "Source record ID")
    if source_fingerprint_sha256 is not None:
        result["source_fingerprint_sha256"] = _sha256(source_fingerprint_sha256)
    validate_evidence_value(result)
    return result


def evidence_absent(state: str, authority: str, reason_code: str) -> dict[str, Any]:
    if state == "PRESENT":
        raise ResearchFactExportError("Use evidence_present for PRESENT evidence")
    result = {
        "authority": _required_text(authority, "Evidence authority"),
        "reason_code": _required_text(reason_code, "Evidence reason code"),
        "state": state,
    }
    validate_evidence_value(result)
    return result


def time_evidence(
    role: str,
    normalized_rfc3339: str,
    authority: str,
    *,
    precision: str = "MILLISECOND",
    raw_value: str | None = None,
    normalization_rule_version: str = "RFC3339_V1",
) -> dict[str, Any]:
    _timestamp(normalized_rfc3339, role)
    result: dict[str, Any] = {
        "authority": _required_text(authority, "Time authority"),
        "normalized_rfc3339": normalized_rfc3339,
        "precision": _required_text(precision, "Time precision"),
        "reason_code": "PRESENT",
        "role": _time_role(role),
        "state": "PRESENT",
        "timezone_or_offset": _offset_text(normalized_rfc3339),
    }
    if raw_value is not None:
        result["raw_value"] = _required_text(raw_value, "Raw time value")
        result["normalization_rule_version"] = _required_text(
            normalization_rule_version, "Time normalization rule version"
        )
    validate_time_evidence(result, expected_role=role)
    return result


def absent_time_evidence(role: str, state: str, authority: str, reason_code: str) -> dict[str, Any]:
    result = evidence_absent(state, authority, reason_code)
    result["role"] = _time_role(role)
    validate_time_evidence(result, expected_role=role)
    return result


def instrument_identity(
    *,
    symbol: Mapping[str, Any],
    asset_type: Mapping[str, Any],
    venue_or_exchange: Mapping[str, Any],
    authoritative_security_id: Mapping[str, Any],
    currency: Mapping[str, Any] | None = None,
    provider_security_ids: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    semantic: dict[str, Any] = {
        "asset_type": dict(asset_type),
        "authoritative_security_id": dict(authoritative_security_id),
        "provider_security_ids": [dict(item) for item in provider_security_ids],
        "symbol": dict(symbol),
        "venue_or_exchange": dict(venue_or_exchange),
    }
    if currency is not None:
        semantic["currency"] = dict(currency)
    result = {
        **semantic,
        "instrument_identity_fingerprint_sha256": fingerprint(semantic),
    }
    validate_instrument_identity(result)
    return result


def outcome_followup_policy(
    *,
    policy_id: str,
    policy_version: str,
    eligibility_mode: str,
    exchange_calendar_id_and_version: str,
    bar_interval_semantic: str,
    source_priority: Sequence[str],
    provider_owner_load_limit: Mapping[str, Any],
    retry_and_finalization_cutoff: Mapping[str, Any],
    policy_seed: str | None = None,
    bucket_count_n: int | None = None,
    selected_bucket_count_k: int | None = None,
) -> dict[str, Any]:
    semantic: dict[str, Any] = {
        "bar_interval_semantic": _required_text(bar_interval_semantic, "Bar interval semantic"),
        "eligibility_mode": eligibility_mode,
        "exchange_calendar_id_and_version": _required_text(
            exchange_calendar_id_and_version, "Exchange calendar identity"
        ),
        "frozen_before_session": True,
        "horizons": list(OUTCOME_HORIZONS),
        "outcome_selection_hindsight": False,
        "policy_id": _required_text(policy_id, "Outcome policy ID"),
        "policy_version": _required_text(policy_version, "Outcome policy version"),
        "provider_owner_load_limit": dict(provider_owner_load_limit),
        "retry_and_finalization_cutoff": dict(retry_and_finalization_cutoff),
        "source_priority": [_required_text(item, "Outcome source identity") for item in source_priority],
    }
    if policy_seed is not None:
        semantic["policy_seed"] = _required_text(policy_seed, "Outcome policy seed")
    if bucket_count_n is not None:
        semantic["bucket_count_n"] = bucket_count_n
    if selected_bucket_count_k is not None:
        semantic["selected_bucket_count_k"] = selected_bucket_count_k
    result = {**semantic, "policy_sha256": fingerprint(semantic)}
    validate_outcome_followup_policy(result)
    return result


def build_envelope(
    *,
    event_type: str,
    stream_id: str,
    session_id: str,
    source_contract: str,
    source_contract_version: str,
    source_event_id: str,
    source_event_fingerprint_sha256: str,
    source_sequence: int,
    event_time: str,
    effective_known_at: str,
    emitted_at: str,
    previous_record_sha256: str,
    records: Sequence[Mapping[str, Any]] = (),
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any]
    if event_type == "SESSION_MANIFEST":
        if manifest is None or records:
            raise ResearchFactExportError("SESSION_MANIFEST requires only a manifest object")
        payload = {"manifest": dict(manifest), "payload_variant": event_type}
    else:
        if manifest is not None:
            raise ResearchFactExportError("Fact variants cannot carry a session manifest")
        payload = {
            "payload_variant": event_type,
            "records": [dict(record) for record in records],
        }
    envelope = {
        "authority": AUTHORITY,
        "effective_known_at": effective_known_at,
        "emitted_at": emitted_at,
        "event_time": event_time,
        "event_type": event_type,
        "execution_authority": EXECUTION_AUTHORITY,
        "payload": payload,
        "payload_sha256": fingerprint(payload),
        "previous_record_sha256": previous_record_sha256,
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "source_contract": source_contract,
        "source_contract_version": source_contract_version,
        "source_event_fingerprint_sha256": source_event_fingerprint_sha256,
        "source_event_id": source_event_id,
        "source_sequence": source_sequence,
        "stream_id": stream_id,
    }
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "event_type",
        "stream_id",
        "session_id",
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
    if set(envelope) != required:
        raise ResearchFactExportError(
            f"Envelope fields differ from ResearchExportEnvelopeV1: {sorted(set(envelope) ^ required)}"
        )
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ResearchFactExportError("Unsupported export schema version")
    event_type = str(envelope["event_type"])
    if event_type not in EVENT_TYPES:
        raise ResearchFactExportError("Unsupported export event type")
    for name in (
        "stream_id",
        "session_id",
        "source_contract",
        "source_contract_version",
        "source_event_id",
    ):
        _required_text(envelope[name], name)
    _sha256(envelope["source_event_fingerprint_sha256"])
    _sha256(envelope["payload_sha256"])
    _sha256(envelope["previous_record_sha256"])
    if not isinstance(envelope["source_sequence"], int) or isinstance(
        envelope["source_sequence"], bool
    ) or envelope["source_sequence"] < 0:
        raise ResearchFactExportError("source_sequence must be a nonnegative integer")
    for name in ("event_time", "effective_known_at", "emitted_at"):
        _timestamp(envelope[name], name)
    if envelope["authority"] != AUTHORITY or envelope["execution_authority"] != EXECUTION_AUTHORITY:
        raise ResearchFactExportError("Export authority must remain RESEARCH_ONLY/NONE")
    payload = envelope["payload"]
    if not isinstance(payload, Mapping):
        raise ResearchFactExportError("Envelope payload must be an object")
    if envelope["payload_sha256"] != fingerprint(payload):
        raise ResearchFactExportError("Envelope payload hash mismatch")
    _reject_forbidden_payload(payload)
    _validate_payload(event_type, payload, str(envelope["source_event_id"]), str(envelope["session_id"]))
    _channel_for_envelope(envelope)


def validate_record(record: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping):
        raise ResearchFactExportError("Research record must be an object")
    record_type = record.get("record_type")
    if not isinstance(record_type, str) or not _RECORD_TYPE.fullmatch(record_type):
        raise ResearchFactExportError("Research record_type is invalid")
    if record_type not in REQUIRED_RECORD_FIELDS:
        raise ResearchFactExportError("Unsupported research record family")
    missing = (COMMON_RECORD_FIELDS | REQUIRED_RECORD_FIELDS[record_type]) - set(record)
    if missing:
        raise ResearchFactExportError(f"{record_type} is missing required fields: {sorted(missing)}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ResearchFactExportError("Research record schema version mismatch")
    validate_identity_ref(record["record_id"])
    validate_identity_ref(record["session_id"], expected_kind="SESSION")
    if not isinstance(record["record_sequence"], int) or isinstance(record["record_sequence"], bool) or record["record_sequence"] < 0:
        raise ResearchFactExportError("record_sequence must be a nonnegative integer")
    _required_text(record["partition_id"], "partition_id")
    _required_text(record["source_owner"], "source_owner")
    validate_evidence_value(record["source_record_identity"])
    _sha256(record["source_fingerprint_sha256"])
    validate_time_evidence(record["recorder_capture_time"], expected_role="RECORDER_CAPTURE_TIME")
    if record["availability"] not in AVAILABILITY_STATES:
        raise ResearchFactExportError("Record availability is invalid")
    _required_text(record["producer_export_envelope_id"], "producer_export_envelope_id")
    _reject_forbidden_payload(record)
    validator = globals()[f"_validate_{record_type.replace('-', '_')}"]
    validator(record)


def validate_evidence_value(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise ResearchFactExportError("Evidence value must be an object")
    for name in ("state", "authority", "reason_code"):
        if name not in value:
            raise ResearchFactExportError(f"Evidence value is missing {name}")
    state = value["state"]
    if state not in AVAILABILITY_STATES:
        raise ResearchFactExportError("Evidence availability state is invalid")
    _required_text(value["authority"], "Evidence authority")
    reason = _required_text(value["reason_code"], "Evidence reason code")
    if state == "PRESENT":
        if "value" not in value or reason != "PRESENT":
            raise ResearchFactExportError("PRESENT evidence requires value and reason_code PRESENT")
    elif "value" in value:
        raise ResearchFactExportError("Non-PRESENT evidence prohibits value")
    if "source_fingerprint_sha256" in value:
        _sha256(value["source_fingerprint_sha256"])


def validate_time_evidence(value: Mapping[str, Any], *, expected_role: str | None = None) -> None:
    if not isinstance(value, Mapping):
        raise ResearchFactExportError("Time evidence must be an object")
    for name in ("state", "authority", "reason_code", "role"):
        if name not in value:
            raise ResearchFactExportError(f"Time evidence is missing {name}")
    if value["state"] not in AVAILABILITY_STATES:
        raise ResearchFactExportError("Time evidence availability state is invalid")
    _required_text(value["authority"], "Time authority")
    reason = _required_text(value["reason_code"], "Time evidence reason code")
    if value["state"] == "PRESENT" and reason != "PRESENT":
        raise ResearchFactExportError("PRESENT time evidence requires reason_code PRESENT")
    if value["state"] != "PRESENT" and "value" in value:
        raise ResearchFactExportError("Non-PRESENT time evidence prohibits value")
    role = _time_role(value.get("role"))
    if expected_role is not None and role != expected_role:
        raise ResearchFactExportError(f"Time role must be {expected_role}")
    if value["state"] == "PRESENT":
        for name in ("normalized_rfc3339", "timezone_or_offset", "precision"):
            _required_text(value.get(name), f"Time evidence {name}")
        _timestamp(value["normalized_rfc3339"], role)
        if value["timezone_or_offset"] != _offset_text(value["normalized_rfc3339"]):
            raise ResearchFactExportError("Time offset does not match normalized timestamp")
        if "raw_value" in value and "normalization_rule_version" not in value:
            raise ResearchFactExportError("Raw time requires a normalization rule version")
    elif "normalized_rfc3339" in value:
        raise ResearchFactExportError("Non-PRESENT time evidence prohibits a normalized time")


def validate_identity_ref(value: Mapping[str, Any], *, expected_kind: str | None = None) -> None:
    if not isinstance(value, Mapping):
        raise ResearchFactExportError("Identity reference must be an object")
    for name in ("identity_kind", "recorder_id", "allocation_mode"):
        _required_text(value.get(name), f"Identity {name}")
    kind = _identity_kind(value["identity_kind"])
    if expected_kind is not None and kind != expected_kind:
        raise ResearchFactExportError(f"Identity kind must be {expected_kind}")
    prefix = f"ar1:{kind.lower()}:"
    recorder_id = value["recorder_id"]
    if not recorder_id.startswith(prefix) or not _SHA256.fullmatch(recorder_id[len(prefix) :]):
        raise ResearchFactExportError("Recorder identity format is invalid")
    if value["allocation_mode"] == "OWNER_WRAPPED":
        for name in ("owner_namespace", "owner_id", "owner_schema_version"):
            _required_text(value.get(name), f"Owner identity {name}")
    elif value["allocation_mode"] == "RECORDER_DURABLE_ALLOCATED":
        _sha256(value.get("logical_key_fingerprint_sha256"))
    else:
        raise ResearchFactExportError("Identity allocation mode is invalid")


def validate_instrument_identity(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise ResearchFactExportError("Instrument identity must be an object")
    required = {
        "instrument_identity_fingerprint_sha256",
        "symbol",
        "asset_type",
        "venue_or_exchange",
        "authoritative_security_id",
    }
    if not required <= set(value):
        raise ResearchFactExportError("Instrument identity is incomplete")
    for name in ("symbol", "asset_type", "venue_or_exchange", "authoritative_security_id"):
        validate_evidence_value(value[name])
    if "currency" in value:
        validate_evidence_value(value["currency"])
    semantic = dict(value)
    claimed = semantic.pop("instrument_identity_fingerprint_sha256")
    if _sha256(claimed) != fingerprint(semantic):
        raise ResearchFactExportError("Instrument identity fingerprint mismatch")


def validate_outcome_followup_policy(policy: Mapping[str, Any]) -> None:
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
    if not required <= set(policy):
        raise ResearchFactExportError("Outcome follow-up policy is incomplete")
    if policy["frozen_before_session"] is not True or policy["outcome_selection_hindsight"] is not False:
        raise ResearchFactExportError("Outcome policy must be frozen and hindsight-free")
    if tuple(policy["horizons"]) != OUTCOME_HORIZONS:
        raise ResearchFactExportError("Outcome policy horizons are not the exact V1 set")
    if policy["eligibility_mode"] not in {"ALL_UNIQUE_INSTRUMENTS", "FIXED_HASH_BUCKET"}:
        raise ResearchFactExportError("Outcome eligibility mode is invalid")
    if policy["eligibility_mode"] == "FIXED_HASH_BUCKET":
        for name in ("policy_seed", "bucket_count_n", "selected_bucket_count_k"):
            if name not in policy:
                raise ResearchFactExportError("Hash-bucket policy is incomplete")
        n = policy["bucket_count_n"]
        k = policy["selected_bucket_count_k"]
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0 or not isinstance(k, int) or isinstance(k, bool) or not 0 <= k <= n:
            raise ResearchFactExportError("Hash-bucket policy bounds are invalid")
    semantic = dict(policy)
    claimed = semantic.pop("policy_sha256")
    if _sha256(claimed) != fingerprint(semantic):
        raise ResearchFactExportError("Outcome policy hash mismatch")
    validate_evidence_value(policy["provider_owner_load_limit"])
    if not isinstance(policy["retry_and_finalization_cutoff"], Mapping):
        raise ResearchFactExportError("Outcome cutoff policy must be an object")


@dataclass(frozen=True)
class AppendReceipt:
    status: str
    channel: str
    source_event_id: str
    envelope_sha256: str
    receipt_sha256: str
    recovered: bool = False


class ResearchFactExportStore:
    """Create-only external partition with receipt chains and immutable cursors."""

    def __init__(
        self,
        export_root: str | Path,
        *,
        market_date: str,
        session_id: str,
        protected_roots: Iterable[str | Path] = (),
        science_custody_roots: Iterable[str | Path] = (),
    ) -> None:
        raw_root = Path(export_root)
        if not raw_root.is_absolute():
            raise ResearchFactExportError("Export root must be an absolute caller path")
        if not _MARKET_DATE.fullmatch(market_date):
            raise ResearchFactExportError("market_date must be YYYY-MM-DD")
        self.export_root = raw_root.resolve(strict=False)
        self.market_date = market_date
        self.session_id = _required_text(session_id, "Session ID")
        self.session_token = hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()
        self.partition = self.export_root / self.market_date / self.session_token
        self._protected_roots = tuple(Path(item).resolve(strict=False) for item in protected_roots)
        self._science_roots = tuple(Path(item).resolve(strict=False) for item in science_custody_roots)
        self._assert_isolated()

    def initialize(self, session_start: Mapping[str, Any]) -> Path:
        self._assert_isolated()
        self._assert_no_link_ancestors(self.export_root)
        required = {
            "session_id",
            "market_date",
            "market_calendar_id_and_version",
            "policy_fingerprint_sha256",
            "config_fingerprint_sha256",
            "runtime_fingerprint_sha256",
            "authority",
            "execution_authority",
        }
        if not required <= set(session_start):
            raise ResearchFactExportError("Session-start manifest is incomplete")
        if session_start["session_id"] != self.session_id or session_start["market_date"] != self.market_date:
            raise ResearchFactExportError("Session-start identity does not match the partition")
        for name in ("policy_fingerprint_sha256", "config_fingerprint_sha256", "runtime_fingerprint_sha256"):
            _sha256(session_start[name])
        if session_start["authority"] != AUTHORITY or session_start["execution_authority"] != EXECUTION_AUTHORITY:
            raise ResearchFactExportError("Session-start authority must remain RESEARCH_ONLY/NONE")
        for area in ("payloads", "receipts", "checkpoints"):
            for channel in CHANNELS:
                (self.partition / area / channel).mkdir(parents=True, exist_ok=True)
        for area in ("conflicts", "manifests"):
            (self.partition / area).mkdir(parents=True, exist_ok=True)
        target = self.partition / "manifests" / "session-start.json"
        encoded = canonical_json_bytes(dict(session_start))
        if target.exists():
            if target.read_bytes() != encoded:
                raise ResearchFactConflict("Conflicting session-start manifest")
            return target
        _write_once(target, encoded)
        return target

    def append(
        self,
        envelope: Mapping[str, Any],
        *,
        _qualification_interrupt_after: str | None = None,
    ) -> AppendReceipt:
        self._require_initialized()
        self._fail_if_conflicted()
        validate_envelope(envelope)
        if envelope["session_id"] != self.session_id:
            raise ResearchFactExportError("Envelope session does not match export partition")
        self.recover()
        index = self._load_index()
        encoded = canonical_json_bytes(dict(envelope))
        envelope_sha = sha256_bytes(encoded)
        source_event_id = str(envelope["source_event_id"])
        existing = index["events"].get(source_event_id)
        if existing is not None:
            if existing["envelope_sha256"] == envelope_sha:
                return AppendReceipt(
                    status="IDEMPOTENT_ACK",
                    channel=existing["channel"],
                    source_event_id=source_event_id,
                    envelope_sha256=envelope_sha,
                    receipt_sha256=existing["receipt_sha256"],
                )
            self._persist_conflict("SOURCE_EVENT_ID_BYTES_DIFFER", source_event_id, existing["envelope_sha256"], envelope_sha)
            raise ResearchFactConflict("Same source event identity has different bytes")
        self._validate_source_chain(envelope, index)
        self._validate_record_identity_conflicts(envelope, index)
        self._validate_cross_record_links(envelope, index)
        channel = _channel_for_envelope(envelope)
        sequence = int(envelope["source_sequence"])
        token = hashlib.sha256(source_event_id.encode("utf-8")).hexdigest()[:20]
        filename = f"{sequence:020d}-{token}.json"
        payload_path = self.partition / "payloads" / channel / filename
        receipt_path = self.partition / "receipts" / channel / filename
        _write_once(payload_path, encoded)
        if _qualification_interrupt_after == "payload":
            raise QualificationInterruption("Offline qualification interrupted after payload")
        receipt = self._commit_receipt(envelope, payload_path, receipt_path, index)
        if _qualification_interrupt_after == "receipt":
            raise QualificationInterruption("Offline qualification interrupted after receipt")
        self._commit_checkpoint(envelope, envelope_sha, receipt, recovered=False)
        return AppendReceipt(
            status="APPENDED",
            channel=channel,
            source_event_id=source_event_id,
            envelope_sha256=envelope_sha,
            receipt_sha256=receipt["receipt_sha256"],
        )

    def recover(self) -> tuple[AppendReceipt, ...]:
        self._require_initialized()
        self._fail_if_conflicted()
        recovered: list[AppendReceipt] = []
        index = self._load_index(allow_payload_without_receipt=True)
        for channel in CHANNELS:
            payloads = {path.name: path for path in sorted((self.partition / "payloads" / channel).glob("*.json"))}
            receipts = {path.name: path for path in sorted((self.partition / "receipts" / channel).glob("*.json"))}
            orphan_receipts = set(receipts) - set(payloads)
            if orphan_receipts:
                raise ResearchFactExportError("Receipt exists without its payload")
            for name in sorted(set(payloads) - set(receipts)):
                path = payloads[name]
                envelope = _read_canonical_object(path)
                validate_envelope(envelope)
                self._validate_source_chain(envelope, index)
                self._validate_record_identity_conflicts(envelope, index)
                receipt = self._commit_receipt(envelope, path, self.partition / "receipts" / channel / name, index)
                self._commit_checkpoint(envelope, sha256_bytes(path.read_bytes()), receipt, recovered=True)
                item = AppendReceipt(
                    status="RECOVERED",
                    channel=channel,
                    source_event_id=envelope["source_event_id"],
                    envelope_sha256=sha256_bytes(path.read_bytes()),
                    receipt_sha256=receipt["receipt_sha256"],
                    recovered=True,
                )
                recovered.append(item)
                index = self._load_index(allow_payload_without_receipt=True)
        self._recover_missing_checkpoints()
        return tuple(recovered)

    def verify(self) -> dict[str, Any]:
        self._require_initialized()
        self._fail_if_conflicted()
        self.recover()
        index = self._load_index()
        self._verify_cross_record_links(index)
        counts = {channel: 0 for channel in CHANNELS}
        record_counts = {record_type: 0 for record_type in RECORD_CHANNELS}
        availability = {state: 0 for state in AVAILABILITY_STATES}
        outcome_horizons = {horizon: 0 for horizon in OUTCOME_HORIZONS}
        for event in index["ordered_events"]:
            counts[event["channel"]] += 1
            envelope = event["envelope"]
            for record in envelope["payload"].get("records", []):
                record_counts[record["record_type"]] += 1
                availability[record["availability"]] += 1
                if record["record_type"] == "outcome-observation":
                    outcome_horizons[record["outcome_semantic"]] += 1
        return {
            "authority": AUTHORITY,
            "channel_counts": counts,
            "channel_heads": index["channel_heads"],
            "conflict_count": 0,
            "coverage_metric_ids": list(COVERAGE_METRIC_IDS),
            "event_count": len(index["ordered_events"]),
            "execution_authority": EXECUTION_AUTHORITY,
            "outcome_horizon_counts": outcome_horizons,
            "record_counts": record_counts,
            "record_state_counts": availability,
            "source_stream_heads": index["stream_heads"],
            "status": "VERIFIED",
        }

    def iter_verified_records(self) -> Iterable[dict[str, Any]]:
        """Yield detached record copies after full receipt/chain verification."""

        self.verify()
        index = self._load_index()
        for event in index["ordered_events"]:
            for record in event["envelope"]["payload"].get("records", []):
                yield json.loads(json.dumps(record, ensure_ascii=False))

    def iter_verified_envelopes(self) -> Iterable[dict[str, Any]]:
        """Yield detached producer envelopes after full receipt/chain verification."""

        self.verify()
        for event in self._load_index()["ordered_events"]:
            yield json.loads(json.dumps(event["envelope"], ensure_ascii=False))

    def manifest_payload(self, *, close_state: str, policy_sha256: str) -> dict[str, Any]:
        snapshot = self.verify()
        return {
            "authority": AUTHORITY,
            "channel_counts": snapshot["channel_counts"],
            "channel_heads": snapshot["channel_heads"],
            "close_state": _required_text(close_state, "Session close state"),
            "coverage_metric_ids": list(COVERAGE_METRIC_IDS),
            "execution_authority": EXECUTION_AUTHORITY,
            "outcome_horizon_counts": snapshot["outcome_horizon_counts"],
            "policy_sha256": _sha256(policy_sha256),
            "record_counts": snapshot["record_counts"],
            "session_id": self.session_id,
            "source_stream_heads": snapshot["source_stream_heads"],
        }

    def _load_index(self, *, allow_payload_without_receipt: bool = False) -> dict[str, Any]:
        events: dict[str, dict[str, Any]] = {}
        records: dict[str, dict[str, Any]] = {}
        ordered_events: list[dict[str, Any]] = []
        channel_heads: dict[str, str] = {channel: ZERO_SHA256 for channel in CHANNELS}
        stream_heads: dict[str, dict[str, Any]] = {}
        for channel in CHANNELS:
            previous_receipt_sha = ZERO_SHA256
            previous_sequence = -1
            payload_dir = self.partition / "payloads" / channel
            receipt_dir = self.partition / "receipts" / channel
            for payload_path in sorted(payload_dir.glob("*.json")):
                receipt_path = receipt_dir / payload_path.name
                envelope = _read_canonical_object(payload_path)
                validate_envelope(envelope)
                if _channel_for_envelope(envelope) != channel:
                    raise ResearchFactExportError("Payload is stored in the wrong channel")
                sequence = int(envelope["source_sequence"])
                if sequence <= previous_sequence:
                    raise ResearchFactExportError("Channel source sequence is not strictly increasing")
                previous_sequence = sequence
                envelope_sha = sha256_bytes(payload_path.read_bytes())
                event_id = envelope["source_event_id"]
                if event_id in events:
                    raise ResearchFactExportError("Duplicate source event identity is stored")
                event_item: dict[str, Any] = {
                    "channel": channel,
                    "envelope": envelope,
                    "envelope_sha256": envelope_sha,
                    "payload_path": payload_path,
                }
                if not receipt_path.exists():
                    if not allow_payload_without_receipt:
                        raise ResearchFactExportError("Payload is missing its receipt")
                    event_item["receipt_sha256"] = ZERO_SHA256
                    events[event_id] = event_item
                    ordered_events.append(event_item)
                    continue
                receipt = _read_canonical_object(receipt_path)
                receipt_sha = sha256_bytes(receipt_path.read_bytes())
                self._verify_receipt(receipt, envelope, envelope_sha, previous_receipt_sha, channel)
                previous_receipt_sha = receipt_sha
                channel_heads[channel] = receipt_sha
                event_item["receipt_sha256"] = receipt_sha
                events[event_id] = event_item
                ordered_events.append(event_item)
                for record in envelope["payload"].get("records", []):
                    record_id = record["record_id"]["recorder_id"]
                    record_sha = fingerprint(record)
                    if record_id in records and records[record_id]["record_sha256"] != record_sha:
                        raise ResearchFactExportError("Stored record identity has conflicting bytes")
                    records[record_id] = {"record": record, "record_sha256": record_sha}
        ordered_events.sort(key=lambda item: (item["envelope"]["stream_id"], item["envelope"]["source_sequence"]))
        for item in ordered_events:
            if item.get("receipt_sha256") == ZERO_SHA256:
                continue
            envelope = item["envelope"]
            stream_id = envelope["stream_id"]
            previous = stream_heads.get(stream_id)
            expected_previous = ZERO_SHA256 if previous is None else previous["envelope_sha256"]
            if envelope["previous_record_sha256"] != expected_previous:
                raise ResearchFactExportError("Source stream chain does not verify")
            if previous is not None and envelope["source_sequence"] <= previous["source_sequence"]:
                raise ResearchFactExportError("Source stream sequence does not increase")
            stream_heads[stream_id] = {
                "envelope_sha256": item["envelope_sha256"],
                "source_event_id": envelope["source_event_id"],
                "source_sequence": envelope["source_sequence"],
            }
        return {
            "channel_heads": channel_heads,
            "events": events,
            "ordered_events": ordered_events,
            "records": records,
            "stream_heads": stream_heads,
        }

    def _validate_source_chain(self, envelope: Mapping[str, Any], index: Mapping[str, Any]) -> None:
        previous = index["stream_heads"].get(envelope["stream_id"])
        expected = ZERO_SHA256 if previous is None else previous["envelope_sha256"]
        if envelope["previous_record_sha256"] != expected:
            raise ResearchFactExportError("Envelope previous_record_sha256 does not match the source stream head")
        if previous is not None and envelope["source_sequence"] <= previous["source_sequence"]:
            raise ResearchFactExportError("Envelope source sequence does not increase")

    def _validate_record_identity_conflicts(self, envelope: Mapping[str, Any], index: Mapping[str, Any]) -> None:
        staged: dict[str, str] = {}
        for record in envelope["payload"].get("records", []):
            record_id = record["record_id"]["recorder_id"]
            record_sha = fingerprint(record)
            existing = index["records"].get(record_id)
            existing_sha = existing["record_sha256"] if existing else staged.get(record_id)
            if existing_sha is not None and existing_sha != record_sha:
                self._persist_conflict("RECORD_ID_BYTES_DIFFER", record_id, existing_sha, record_sha)
                raise ResearchFactConflict("Same record identity has different bytes")
            staged[record_id] = record_sha

    @staticmethod
    def _validate_cross_record_links(envelope: Mapping[str, Any], index: Mapping[str, Any]) -> None:
        for record in envelope["payload"].get("records", []):
            if record["record_type"] == "decision-event":
                observation_id = record["observation_id"]["recorder_id"]
                observation_item = index["records"].get(observation_id)
                if observation_item is None or observation_item["record"]["record_type"] != "candidate-observation":
                    raise ResearchFactExportError("Decision must link an already accepted exact observation")
                observation = observation_item["record"]
                if observation["candidate_or_setup_identity"] != record["candidate_or_setup_identity"]:
                    raise ResearchFactExportError("Decision candidate/setup identity does not match its observation")
                if observation["outcome_eligibility"]["commitment_payload_sha256"] != record["outcome_eligibility_commitment_sha256"]:
                    raise ResearchFactExportError("Decision eligibility hash does not match its observation commitment")
            if record["record_type"] == "outcome-observation":
                decision_id = record["decision_id"]["recorder_id"]
                observation_id = record["observation_id"]["recorder_id"]
                decision_item = index["records"].get(decision_id)
                observation_item = index["records"].get(observation_id)
                if decision_item is None or decision_item["record"]["record_type"] != "decision-event":
                    raise ResearchFactExportError("Outcome must link an already accepted frozen decision")
                if observation_item is None or observation_item["record"]["record_type"] != "candidate-observation":
                    raise ResearchFactExportError("Outcome must link an already accepted exact observation")
                decision = decision_item["record"]
                observation = observation_item["record"]
                if record["decision_payload_sha256"] != decision_item["record_sha256"]:
                    raise ResearchFactExportError("Outcome decision payload hash does not match frozen decision bytes")
                if record["eligibility_commitment_sha256"] != observation["outcome_eligibility"]["commitment_payload_sha256"]:
                    raise ResearchFactExportError("Outcome eligibility hash does not match pre-outcome commitment")
                if decision["observation_id"] != record["observation_id"] or decision["candidate_or_setup_identity"] != record["candidate_or_setup_identity"]:
                    raise ResearchFactExportError("Outcome identity graph does not match the frozen decision")

    def _verify_cross_record_links(self, index: Mapping[str, Any]) -> None:
        for item in index["ordered_events"]:
            self._validate_cross_record_links(item["envelope"], index)

    def _commit_receipt(
        self,
        envelope: Mapping[str, Any],
        payload_path: Path,
        receipt_path: Path,
        index: Mapping[str, Any],
    ) -> dict[str, Any]:
        channel = _channel_for_envelope(envelope)
        previous = index["channel_heads"][channel]
        previous_evidence = (
            evidence_absent("NOT_APPLICABLE", "EXPORT_STORE", "GENESIS")
            if previous == ZERO_SHA256
            else evidence_present(previous, "EXPORT_STORE")
        )
        committed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        receipt = {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "channel": channel,
            "committed_at": time_evidence("RECORDER_CAPTURE_TIME", committed_at, "EXPORT_STORE"),
            "envelope_sha256": sha256_bytes(payload_path.read_bytes()),
            "payload_sha256": envelope["payload_sha256"],
            "previous_receipt_sha256": previous_evidence,
            "receipt_version": RECEIPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "source_event_fingerprint_sha256": envelope["source_event_fingerprint_sha256"],
            "source_event_id": envelope["source_event_id"],
            "source_sequence": envelope["source_sequence"],
        }
        _write_once(receipt_path, canonical_json_bytes(receipt))
        return {**receipt, "receipt_sha256": sha256_bytes(receipt_path.read_bytes())}

    def _commit_checkpoint(
        self,
        envelope: Mapping[str, Any],
        envelope_sha: str,
        receipt: Mapping[str, Any],
        *,
        recovered: bool,
    ) -> None:
        channel = _channel_for_envelope(envelope)
        token = hashlib.sha256(envelope["source_event_id"].encode("utf-8")).hexdigest()[:20]
        path = self.partition / "checkpoints" / channel / f"{envelope['source_sequence']:020d}-{token}.json"
        checkpoint = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "last_safe_cursor": {
                "channel": channel,
                "envelope_sha256": envelope_sha,
                "receipt_sha256": receipt["receipt_sha256"],
                "source_event_id": envelope["source_event_id"],
                "source_sequence": envelope["source_sequence"],
            },
            "recovered_after_interruption": recovered,
        }
        encoded = canonical_json_bytes(checkpoint)
        if path.exists():
            existing = _read_canonical_object(path)
            if existing["last_safe_cursor"] != checkpoint["last_safe_cursor"]:
                raise ResearchFactExportError("Immutable checkpoint cursor conflicts")
            return
        _write_once(path, encoded)

    def _recover_missing_checkpoints(self) -> None:
        for channel in CHANNELS:
            for receipt_path in sorted((self.partition / "receipts" / channel).glob("*.json")):
                checkpoint_path = self.partition / "checkpoints" / channel / receipt_path.name
                if checkpoint_path.exists():
                    continue
                receipt = _read_canonical_object(receipt_path)
                payload_path = self.partition / "payloads" / channel / receipt_path.name
                envelope = _read_canonical_object(payload_path)
                receipt_with_hash = {**receipt, "receipt_sha256": sha256_bytes(receipt_path.read_bytes())}
                self._commit_checkpoint(
                    envelope,
                    sha256_bytes(payload_path.read_bytes()),
                    receipt_with_hash,
                    recovered=True,
                )

    @staticmethod
    def _verify_receipt(
        receipt: Mapping[str, Any],
        envelope: Mapping[str, Any],
        envelope_sha: str,
        previous_receipt_sha: str,
        channel: str,
    ) -> None:
        if receipt.get("receipt_version") != RECEIPT_VERSION or receipt.get("canonicalization_version") != CANONICALIZATION_VERSION:
            raise ResearchFactExportError("Receipt version is invalid")
        if receipt.get("channel") != channel or receipt.get("schema_version") != SCHEMA_VERSION:
            raise ResearchFactExportError("Receipt channel/schema mismatch")
        if receipt.get("source_event_id") != envelope["source_event_id"] or receipt.get("source_sequence") != envelope["source_sequence"]:
            raise ResearchFactExportError("Receipt source identity mismatch")
        if receipt.get("envelope_sha256") != envelope_sha or receipt.get("payload_sha256") != envelope["payload_sha256"]:
            raise ResearchFactExportError("Receipt payload hash mismatch")
        if receipt.get("source_event_fingerprint_sha256") != envelope["source_event_fingerprint_sha256"]:
            raise ResearchFactExportError("Receipt source hash mismatch")
        previous = receipt.get("previous_receipt_sha256")
        validate_evidence_value(previous)
        expected = None if previous_receipt_sha == ZERO_SHA256 else previous_receipt_sha
        actual = previous.get("value") if previous["state"] == "PRESENT" else None
        if actual != expected:
            raise ResearchFactExportError("Receipt chain does not verify")
        validate_time_evidence(receipt.get("committed_at"), expected_role="RECORDER_CAPTURE_TIME")

    def _persist_conflict(self, conflict_type: str, identity: str, accepted_sha: str, incoming_sha: str) -> None:
        conflict = {
            "accepted_sha256": accepted_sha,
            "conflict_type": conflict_type,
            "detected_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "identity": identity,
            "incoming_sha256": incoming_sha,
            "resolution": "FAIL_CLOSED_NO_REWRITE",
        }
        path = self.partition / "conflicts" / f"{uuid.uuid4().hex}.json"
        _write_once(path, canonical_json_bytes(conflict))

    def _fail_if_conflicted(self) -> None:
        conflict_dir = self.partition / "conflicts"
        if conflict_dir.exists() and any(conflict_dir.glob("*.json")):
            raise ResearchFactConflict("Export partition contains an unresolved immutable conflict")

    def _require_initialized(self) -> None:
        if not (self.partition / "manifests" / "session-start.json").is_file():
            raise ResearchFactExportError("Export partition has not been explicitly initialized")
        self._assert_isolated()
        self._assert_no_link_ancestors(self.partition)

    def _assert_isolated(self) -> None:
        for protected in (*self._protected_roots, *self._science_roots):
            if _paths_overlap(self.export_root, protected):
                raise ResearchFactExportError("Export root overlaps a protected or Science custody root")

    @staticmethod
    def _assert_no_link_ancestors(path: Path) -> None:
        current = path
        while True:
            if current.exists():
                metadata = current.lstat()
                attributes = getattr(metadata, "st_file_attributes", 0)
                if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                    raise ResearchFactExportError("Export path may not traverse a link/reparse point")
            if current.parent == current:
                break
            current = current.parent


def _channel_for_envelope(envelope: Mapping[str, Any]) -> str:
    event_type = str(envelope["event_type"])
    if event_type != "MARKET_FACT":
        return EVENT_CHANNELS[event_type]
    record_types = {
        str(record["record_type"])
        for record in envelope["payload"].get("records", [])
    }
    if record_types == {"market-snapshot"}:
        return "market"
    if record_types == {"outcome-observation"}:
        return "outcome"
    raise ResearchFactExportError(
        "MARKET_FACT must separate market snapshots from outcome observations so receipt channels remain independent"
    )


def _validate_payload(event_type: str, payload: Mapping[str, Any], envelope_id: str, session_id: str) -> None:
    if payload.get("payload_variant") != event_type:
        raise ResearchFactExportError("Payload variant does not match event type")
    if event_type == "SESSION_MANIFEST":
        if set(payload) != {"payload_variant", "manifest"} or not isinstance(payload["manifest"], Mapping):
            raise ResearchFactExportError("Session manifest payload is malformed")
        if payload["manifest"].get("authority") != AUTHORITY or payload["manifest"].get("execution_authority") != EXECUTION_AUTHORITY:
            raise ResearchFactExportError("Session manifest authority is invalid")
        return
    if set(payload) != {"payload_variant", "records"} or not isinstance(payload["records"], list) or not payload["records"]:
        raise ResearchFactExportError("Fact payload requires a nonempty records array")
    allowed = EVENT_RECORD_TYPES[event_type]
    for record in payload["records"]:
        validate_record(record)
        if record["record_type"] not in allowed:
            raise ResearchFactExportError("Record family is not allowed in this payload variant")
        if record["producer_export_envelope_id"] != envelope_id:
            raise ResearchFactExportError("Record does not bind its producer export envelope")
        if record["session_id"]["recorder_id"] != session_id:
            raise ResearchFactExportError("Record session identity does not match envelope session")
    if event_type == "DISCOVERY_CYCLE":
        _validate_discovery_inventory(payload["records"])
    if event_type == "DECISION_FACT":
        _validate_decision_links(payload["records"])


def _validate_discovery_inventory(records: Sequence[Mapping[str, Any]]) -> None:
    cycles = [record for record in records if record["record_type"] == "discovery-cycle"]
    observations = [record for record in records if record["record_type"] == "candidate-observation"]
    if len(cycles) != 1:
        raise ResearchFactExportError("A discovery export must carry exactly one natural cycle")
    cycle = cycles[0]
    cycle_id = cycle["discovery_cycle_id"]["recorder_id"]
    linked = [record for record in observations if record["discovery_cycle_id"]["recorder_id"] == cycle_id]
    linked.sort(key=lambda item: item["source_row_ordinal"])
    ids = [item["observation_id"]["recorder_id"] for item in linked]
    declared = [item["recorder_id"] for item in cycle["observation_ids_in_source_order"]]
    if len(linked) != cycle["returned_row_count"] or ids != declared:
        raise ResearchFactExportError("Discovery denominator row count/order does not reconcile")
    if [item["source_row_ordinal"] for item in linked] != list(range(len(linked))):
        raise ResearchFactExportError("Discovery row ordinals must be exact zero-based source order")


def _validate_decision_links(records: Sequence[Mapping[str, Any]]) -> None:
    decisions = {
        record["decision_id"]["recorder_id"]: record
        for record in records
        if record["record_type"] == "decision-event"
    }
    if not decisions:
        raise ResearchFactExportError("A decision export requires a decision-event")
    for record in records:
        if record["record_type"] == "reference-plan" and record["decision_id"]["recorder_id"] not in decisions:
            raise ResearchFactExportError("Reference plan is not linked to a decision in the same frozen export")


def _validate_discovery_cycle(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["discovery_cycle_id"], expected_kind="DISCOVERY_CYCLE")
    if record["record_id"] != record["discovery_cycle_id"]:
        raise ResearchFactExportError("Discovery record identity mismatch")
    if record["cycle_state"] not in {"COMPLETE", "ZERO_RESULT", "PARTIAL", "FAILED"}:
        raise ResearchFactExportError("Discovery cycle state is invalid")
    _sha256(record["query_or_policy_fingerprint_sha256"])
    validate_time_evidence(record["discovery_time"], expected_role="DISCOVERY_TIME")
    validate_time_evidence(record["provider_received_at"], expected_role="PROVIDER_RECEIVED_AT")
    if not isinstance(record["returned_row_count"], int) or isinstance(record["returned_row_count"], bool) or record["returned_row_count"] < 0:
        raise ResearchFactExportError("Discovery returned_row_count is invalid")
    validate_evidence_value(record["row_order_complete"])
    validate_evidence_value(record["completeness"])
    for identity in record["observation_ids_in_source_order"]:
        validate_identity_ref(identity, expected_kind="OBSERVATION")
    for identity in record["provider_health_event_ids"]:
        validate_identity_ref(identity, expected_kind="PROVIDER_HEALTH_EVENT")
    if not isinstance(record["zero_result"], bool):
        raise ResearchFactExportError("Discovery zero_result must be boolean")
    if record["cycle_state"] == "ZERO_RESULT" and not (
        record["returned_row_count"] == 0 and record["zero_result"] and not record["observation_ids_in_source_order"]
    ):
        raise ResearchFactExportError("ZERO_RESULT cycle invariants failed")
    if record["cycle_state"] == "FAILED" and record["zero_result"]:
        raise ResearchFactExportError("FAILED cycle may not masquerade as zero result")


def _validate_candidate_observation(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["observation_id"], expected_kind="OBSERVATION")
    if record["record_id"] != record["observation_id"]:
        raise ResearchFactExportError("Observation record identity mismatch")
    validate_identity_ref(record["discovery_cycle_id"], expected_kind="DISCOVERY_CYCLE")
    if record["candidate_or_setup_identity"]["identity_kind"] not in {"CANDIDATE_MEMBER", "SETUP"}:
        raise ResearchFactExportError("Observation must preserve candidate-member or setup identity")
    validate_identity_ref(record["candidate_or_setup_identity"])
    validate_instrument_identity(record["instrument_identity"])
    validate_evidence_value(record["rank"])
    validate_time_evidence(record["discovery_time"], expected_role="DISCOVERY_TIME")
    if not isinstance(record["candidate_facts"], Mapping):
        raise ResearchFactExportError("Candidate facts must be an object")
    if set(record["candidate_facts"]) != CANDIDATE_FACT_FIELDS:
        raise ResearchFactExportError("Candidate facts must account for every V1 fact field")
    for value in record["candidate_facts"].values():
        validate_evidence_value(value)
    if not isinstance(record["materially_evaluated"], bool) or not isinstance(record["rejection_or_gap_reasons"], list):
        raise ResearchFactExportError("Observation evaluation evidence is invalid")
    _validate_eligibility_commitment(record["outcome_eligibility"])
    if record["outcome_eligibility"]["instrument_identity_fingerprint_sha256"] != record["instrument_identity"]["instrument_identity_fingerprint_sha256"]:
        raise ResearchFactExportError("Outcome eligibility instrument identity does not match the observation")
    if record["outcome_eligibility"]["committed_at"]["state"] != "PRESENT":
        raise ResearchFactExportError("Outcome eligibility commitment time must be present")
    if _timestamp(
        record["outcome_eligibility"]["committed_at"]["normalized_rfc3339"],
        "Eligibility commitment",
    ) > _timestamp(record["discovery_time"]["normalized_rfc3339"], "Discovery time"):
        raise ResearchFactExportError("Outcome eligibility must be committed at first observation, not later")
    for catalyst in record.get("catalyst_identities", []):
        required = {
            "catalyst_id",
            "source",
            "source_event_time",
            "source_publication_time",
            "provider_known_at",
            "provider_received_at",
        }
        if not isinstance(catalyst, Mapping) or not required <= set(catalyst):
            raise ResearchFactExportError("Catalyst pass-through identity/time evidence is incomplete")
        _required_text(catalyst["catalyst_id"], "Catalyst ID")
        _required_text(catalyst["source"], "Catalyst source")
        for name, role in (
            ("source_event_time", "SOURCE_EVENT_TIME"),
            ("source_publication_time", "SOURCE_PUBLICATION_TIME"),
            ("provider_known_at", "PROVIDER_KNOWN_AT"),
            ("provider_received_at", "PROVIDER_RECEIVED_AT"),
        ):
            validate_time_evidence(catalyst[name], expected_role=role)


def _validate_decision_event(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["decision_id"], expected_kind="DECISION")
    if record["record_id"] != record["decision_id"]:
        raise ResearchFactExportError("Decision record identity mismatch")
    validate_identity_ref(record["observation_id"], expected_kind="OBSERVATION")
    validate_identity_ref(record["candidate_or_setup_identity"])
    if record["decision_state"] not in {"READY", "BLOCKED", "REJECTED", "MISSED", "NO_PLAN", "TRADEPLAN"}:
        raise ResearchFactExportError("Decision state is invalid")
    if not isinstance(record["reason_codes"], list) or not record["reason_codes"]:
        raise ResearchFactExportError("Decision requires explicit versioned reason codes")
    validate_time_evidence(record["decision_time"], expected_role="DECISION_TIME")
    validate_time_evidence(record["decision_cutoff"], expected_role="DECISION_CUTOFF")
    cutoff = _timestamp(record["decision_cutoff"]["normalized_rfc3339"], "DECISION_CUTOFF")
    if _timestamp(record["decision_time"]["normalized_rfc3339"], "DECISION_TIME") < cutoff:
        raise ResearchFactExportError("Decision time may not precede its cutoff")
    if not isinstance(record["known_at_evidence_refs"], list):
        raise ResearchFactExportError("known_at_evidence_refs must be an array")
    for ref in record["known_at_evidence_refs"]:
        if not isinstance(ref, Mapping) or not {"record_id", "evidence_field_path", "known_at", "payload_sha256"} <= set(ref):
            raise ResearchFactExportError("Known-at evidence reference is incomplete")
        validate_identity_ref(ref["record_id"])
        validate_time_evidence(ref["known_at"])
        known = ref["known_at"]
        if known["state"] != "PRESENT" or known["role"] not in {"PROVIDER_KNOWN_AT", "PROVIDER_RECEIVED_AT"}:
            raise ResearchFactExportError("Decision-known evidence requires labeled known/received time")
        if _timestamp(known["normalized_rfc3339"], known["role"]) > cutoff:
            raise ResearchFactExportError("Post-cutoff evidence cannot enter a frozen decision")
        _sha256(ref["payload_sha256"])
    validate_evidence_value(record["strategy_identity"])
    for name in (
        "decision_policy_fingerprint_sha256",
        "config_fingerprint_sha256",
        "runtime_fingerprint_sha256",
        "outcome_eligibility_commitment_sha256",
    ):
        _sha256(record[name])
    for name in ("market_snapshot_id", "tradeplan_id", "reference_plan_id"):
        validate_evidence_value(record[name])
    if record["decision_state"] in {"NO_PLAN", "REJECTED", "BLOCKED", "MISSED"}:
        if record["tradeplan_id"]["state"] != "NOT_APPLICABLE" or record["reference_plan_id"]["state"] != "NOT_APPLICABLE":
            raise ResearchFactExportError("No-plan decision state requires NOT_APPLICABLE plan references")


def _validate_market_snapshot(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["market_snapshot_id"], expected_kind="MARKET_SNAPSHOT")
    if record["record_id"] != record["market_snapshot_id"]:
        raise ResearchFactExportError("Market snapshot record identity mismatch")
    if record["snapshot_kind"] not in {"DECISION_SNAPSHOT", "CANONICAL_MINUTE_BAR"}:
        raise ResearchFactExportError("Market snapshot kind is invalid")
    validate_instrument_identity(record["instrument_identity"])
    for name in ("observation_id", "decision_id", "outcome_series_id"):
        validate_evidence_value(record[name])
    validate_time_evidence(record["source_event_time"], expected_role="SOURCE_EVENT_TIME")
    validate_time_evidence(record["provider_known_at"], expected_role="PROVIDER_KNOWN_AT")
    validate_time_evidence(record["provider_received_at"], expected_role="PROVIDER_RECEIVED_AT")
    if set(record["market_facts"]) != MARKET_FACT_FIELDS:
        raise ResearchFactExportError("Market facts must account for every V1 fact field")
    for value in record["market_facts"].values():
        validate_evidence_value(value)
    _sha256(record["source_market_fact_fingerprint_sha256"])


def _validate_reference_plan(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["reference_plan_id"], expected_kind="REFERENCE_PLAN")
    if record["record_id"] != record["reference_plan_id"]:
        raise ResearchFactExportError("Reference plan record identity mismatch")
    validate_identity_ref(record["tradeplan_id"], expected_kind="TRADEPLAN")
    validate_identity_ref(record["decision_id"], expected_kind="DECISION")
    validate_identity_ref(record["candidate_or_setup_identity"])
    _sha256(record["plan_source_fingerprint_sha256"])
    validate_time_evidence(record["plan_created_at"], expected_role="DECISION_TIME")
    for name in ("entry", "stop", "t1", "t2"):
        validate_evidence_value(record[name])


def _validate_provider_health_event(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["provider_health_event_id"], expected_kind="PROVIDER_HEALTH_EVENT")
    if record["record_id"] != record["provider_health_event_id"]:
        raise ResearchFactExportError("Provider-health record identity mismatch")
    validate_time_evidence(record["source_event_time"], expected_role="SOURCE_EVENT_TIME")
    validate_time_evidence(record["provider_received_at"], expected_role="PROVIDER_RECEIVED_AT")
    for identity in record["affected_record_ids"]:
        validate_identity_ref(identity)
    if not isinstance(record["attempt_number"], int) or isinstance(record["attempt_number"], bool) or record["attempt_number"] < 1:
        raise ResearchFactExportError("Provider-health attempt_number is invalid")
    if not isinstance(record["terminal"], bool) or record["secret_material_present"] is not False:
        raise ResearchFactExportError("Provider-health record must prove no secret material")


def _validate_outcome_observation(record: Mapping[str, Any]) -> None:
    validate_identity_ref(record["outcome_observation_id"], expected_kind="OUTCOME_OBSERVATION")
    if record["record_id"] != record["outcome_observation_id"]:
        raise ResearchFactExportError("Outcome record identity mismatch")
    for name, kind in (
        ("outcome_series_id", "OUTCOME_SERIES"),
        ("decision_id", "DECISION"),
        ("observation_id", "OBSERVATION"),
    ):
        validate_identity_ref(record[name], expected_kind=kind)
    validate_identity_ref(record["candidate_or_setup_identity"])
    for name in (
        "decision_payload_sha256",
        "eligibility_commitment_sha256",
        "canonical_path_fingerprint_sha256",
        "linkage_receipt_sha256",
    ):
        _sha256(record[name])
    if record["outcome_semantic"] not in OUTCOME_HORIZONS:
        raise ResearchFactExportError("Outcome semantic is not required by V1")
    validate_time_evidence(record["target_time"], expected_role="OUTCOME_TIME")
    validate_time_evidence(record["outcome_time"], expected_role="OUTCOME_TIME")
    if (
        record["target_time"]["state"] == "PRESENT"
        and record["outcome_time"]["state"] == "PRESENT"
        and _timestamp(record["outcome_time"]["normalized_rfc3339"], "Outcome time")
        < _timestamp(record["target_time"]["normalized_rfc3339"], "Outcome target time")
    ):
        raise ResearchFactExportError("Outcome time may not precede its frozen target time")
    validate_evidence_value(record["outcome_value"])
    if record["outcome_state"] not in AVAILABILITY_STATES:
        raise ResearchFactExportError("Outcome state is invalid")
    if record["outcome_value"]["state"] != record["outcome_state"]:
        raise ResearchFactExportError("Outcome value/state mismatch")
    for identity in record["canonical_bar_record_ids"]:
        validate_identity_ref(identity, expected_kind="MARKET_SNAPSHOT")
    validate_evidence_value(record["path_completeness"])
    if record["outcome_state"] == "SESSION_TRUNCATED" and record["outcome_value"]["state"] != "SESSION_TRUNCATED":
        raise ResearchFactExportError("Truncated outcome may not fabricate a value")
    if record["outcome_semantic"] in {"MFE", "MAE"} and record["outcome_state"] == "PRESENT" and not record["canonical_bar_record_ids"]:
        raise ResearchFactExportError("MFE/MAE requires canonical path inputs")


def _validate_eligibility_commitment(value: Mapping[str, Any]) -> None:
    required = {
        "policy_id",
        "policy_version",
        "policy_sha256",
        "eligibility_state",
        "first_observation_id",
        "instrument_identity_fingerprint_sha256",
        "committed_at",
        "commitment_payload_sha256",
    }
    if not isinstance(value, Mapping) or not required <= set(value):
        raise ResearchFactExportError("Outcome eligibility commitment is incomplete")
    if value["eligibility_state"] not in {"ELIGIBLE", "CAPACITY_EXCLUDED"}:
        raise ResearchFactExportError("Outcome eligibility state is invalid")
    validate_identity_ref(value["first_observation_id"], expected_kind="OBSERVATION")
    validate_time_evidence(value["committed_at"])
    for name in ("policy_sha256", "instrument_identity_fingerprint_sha256", "commitment_payload_sha256"):
        _sha256(value[name])
    if value["eligibility_state"] == "CAPACITY_EXCLUDED" and not {"deterministic_selection_token", "capacity_reason_code"} <= set(value):
        raise ResearchFactExportError("Capacity exclusion requires deterministic evidence")


def _validate_canonical_value(value: Any, *, path: str = "$") -> None:
    if value is None:
        raise ResearchFactExportError(f"Unqualified null is prohibited at {path}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResearchFactExportError(f"NaN/Infinity is prohibited at {path}")
        raise ResearchFactExportError(f"Floating-point values are prohibited; use decimal strings at {path}")
    if isinstance(value, (str, bool, int)):
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ResearchFactExportError(f"Canonical object keys must be nonempty strings at {path}")
            _validate_canonical_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_canonical_value(child, path=f"{path}[{index}]")
        return
    raise ResearchFactExportError(f"Unsupported canonical value at {path}: {type(value).__name__}")


def _reject_forbidden_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _FORBIDDEN_PAYLOAD_KEYS:
                raise ResearchFactExportError(f"Forbidden authority/capability field at {path}.{key}")
            _reject_forbidden_payload(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_payload(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and (value.startswith("sk-") or value.lower().startswith("bearer ")):
        raise ResearchFactExportError(f"Secret-like value is prohibited at {path}")


def _identity_kind(value: Any) -> str:
    kind = _required_text(value, "Identity type").upper()
    if kind not in IDENTITY_TYPES:
        raise ResearchFactExportError(f"Unsupported identity type: {kind}")
    return kind


def _time_role(value: Any) -> str:
    role = _required_text(value, "Time role").upper()
    if role not in TIME_ROLES:
        raise ResearchFactExportError(f"Unsupported time role: {role}")
    return role


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchFactExportError(f"{label} is required")
    return value.strip()


def _sha256(value: Any) -> str:
    normalized = _required_text(value, "SHA-256").lower()
    if not _SHA256.fullmatch(normalized):
        raise ResearchFactExportError("SHA-256 must be 64 lowercase hexadecimal characters")
    return normalized


def _timestamp(value: Any, label: str) -> datetime:
    text = _required_text(value, label)
    if not (text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text)):
        raise ResearchFactExportError(f"{label} requires an explicit RFC3339 offset")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ResearchFactExportError(f"{label} is not RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchFactExportError(f"{label} requires an explicit offset")
    return parsed


def _offset_text(value: str) -> str:
    if value.endswith("Z"):
        return "Z"
    return value[-6:]


def _paths_overlap(left: Path, right: Path) -> bool:
    left_text = os.path.normcase(str(left.resolve(strict=False)))
    right_text = os.path.normcase(str(right.resolve(strict=False)))
    try:
        return os.path.commonpath((left_text, right_text)) in {left_text, right_text}
    except ValueError:
        return False


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ResearchFactConflict(f"Create-only artifact already exists: {path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.stat().st_nlink != 1:
            raise ResearchFactExportError("Export artifact has an unsafe hard-link count")
    except Exception:
        raise


def _read_canonical_object(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchFactExportError(f"Malformed export artifact: {path.name}") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != data:
        raise ResearchFactExportError(f"Noncanonical or tampered export artifact: {path.name}")
    return value


__all__ = [
    "AUTHORITY",
    "AVAILABILITY_STATES",
    "AppendReceipt",
    "CANONICALIZATION_VERSION",
    "COVERAGE_METRIC_IDS",
    "EVENT_TYPES",
    "EXECUTION_AUTHORITY",
    "IDENTITY_TYPES",
    "OUTCOME_HORIZONS",
    "QualificationInterruption",
    "ResearchFactConflict",
    "ResearchFactExportError",
    "ResearchFactExportStore",
    "SCHEMA_VERSION",
    "TIME_ROLES",
    "ZERO_SHA256",
    "absent_time_evidence",
    "build_envelope",
    "canonical_json_bytes",
    "evidence_absent",
    "evidence_present",
    "fingerprint",
    "instrument_identity",
    "outcome_followup_policy",
    "owner_identity",
    "recorder_identity",
    "sha256_bytes",
    "time_evidence",
    "validate_envelope",
    "validate_evidence_value",
    "validate_identity_ref",
    "validate_instrument_identity",
    "validate_outcome_followup_policy",
    "validate_record",
    "validate_time_evidence",
]
