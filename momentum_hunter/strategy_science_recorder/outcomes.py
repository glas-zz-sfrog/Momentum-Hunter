"""Structurally separate, offline outcome-attachment validation.

The helpers consume caller-supplied bytes only.  They cannot retrieve bars,
contact a provider, or alter a frozen discovery/decision payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    parse_rfc3339,
    require_sha256,
    sha256_hex,
    strict_json_loads,
)
from .contract import (
    AUTHORITY,
    EXECUTION_AUTHORITY,
    GENESIS_SHA256,
    HASH_ALGORITHM,
    HASH_UNIT,
    HORIZONS,
    PREVIOUS_HASH_TARGET,
    PROVIDER_DERIVED_TERMINAL_OUTCOME_STATES,
    RecorderContractError,
    SCHEMA_VERSION,
    SOURCE_SEQUENCE_SCOPE,
    evidence_instant,
    require_evidence_value,
    require_exact_fields,
    require_identity,
    require_time_evidence,
    reject_prohibited_fields,
)


OUTCOME_ATTACHMENT_CONTRACT = "OutcomeAttachmentV1"
SCIENCE_OFFLINE_OUTCOME_PROFILE = "ARGUS_SCIENCE_OFFLINE_OUTCOME_ATTACHMENT_V1"

@dataclass(frozen=True)
class ValidatedOutcomeAttachment:
    raw_bytes: bytes
    raw_sha256: str
    stream_id: str
    session_id: Mapping[str, object]
    source_owner: str
    source_event_id: str
    source_sequence: int
    previous_record_sha256: str
    observed_at: str
    payload_sha256: str
    payload: Mapping[str, object]


def _text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise RecorderContractError(f"{field} must be a nonempty string.")
    return item


def outcome_linkage_sha256(payload: Mapping[str, object]) -> str:
    material = dict(payload)
    material.pop("linkage_receipt_sha256", None)
    return sha256_hex(canonical_json_bytes(material))


def outcome_series_binding_sha256(payload: Mapping[str, object]) -> str:
    """Bind one exact series identity to its ordered canonical bar bytes."""

    material = {
        "canonical_bar_payload_sha256s": payload.get(
            "canonical_bar_payload_sha256s"
        ),
        "canonical_bar_record_ids": payload.get("canonical_bar_record_ids"),
        "outcome_series_id": payload.get("outcome_series_id"),
    }
    return sha256_hex(canonical_json_bytes(material))


def validate_outcome_payload(payload: Mapping[str, object]) -> None:
    required = {
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
        "canonical_series_fingerprint_sha256",
        "canonical_bar_record_ids",
        "canonical_bar_payload_sha256s",
        "path_completeness",
        "transform_version",
        "linkage_receipt_sha256",
    }
    optional = {
        "reference_price",
        "reference_price_market_snapshot_id",
        "return_value",
        "mfe_value",
        "mae_value",
        "truncation_reason_code",
        "provider_health_event_ids",
        "attempt_receipt_ids",
    }
    require_exact_fields(
        payload,
        required=required,
        optional=optional,
        label="outcome payload",
    )
    require_identity(
        payload["outcome_observation_id"],
        "outcome_observation_id",
        kinds=frozenset({"OUTCOME_OBSERVATION_ID"}),
    )
    require_identity(
        payload["outcome_series_id"],
        "outcome_series_id",
        kinds=frozenset({"OUTCOME_SERIES_ID"}),
    )
    require_identity(
        payload["decision_id"], "decision_id", kinds=frozenset({"DECISION_ID"})
    )
    require_identity(
        payload["observation_id"],
        "observation_id",
        kinds=frozenset({"OBSERVATION_ID"}),
    )
    require_identity(
        payload["candidate_or_setup_identity"],
        "candidate_or_setup_identity",
        kinds=frozenset({"CANDIDATE_MEMBER", "SETUP"}),
    )
    for field in (
        "decision_payload_sha256",
        "eligibility_commitment_sha256",
        "canonical_series_fingerprint_sha256",
        "linkage_receipt_sha256",
    ):
        require_sha256(payload[field], field)
    if payload["outcome_semantic"] not in HORIZONS:
        raise RecorderContractError("Unsupported outcome semantic.")
    if payload["outcome_semantic_version"] != SCHEMA_VERSION:
        raise RecorderContractError("Unsupported outcome semantic version.")
    target_evidence = require_time_evidence(payload["target_time"], "target_time")
    if target_evidence["state"] != "PRESENT":
        raise RecorderContractError("Outcome target_time must preserve the exact target instant.")
    require_time_evidence(payload["outcome_time"], "outcome_time", role="OUTCOME_TIME")
    target = payload["target_time"]
    observed = payload["outcome_time"]
    if (
        isinstance(target, Mapping)
        and isinstance(observed, Mapping)
        and target.get("state") == "PRESENT"
        and observed.get("state") == "PRESENT"
        and evidence_instant(observed, "outcome_time")
        < evidence_instant(target, "target_time")
    ):
        raise RecorderContractError("Outcome time cannot precede its target time.")
    outcome_value = require_evidence_value(payload["outcome_value"], "outcome_value", value_kind="decimal")
    path_fingerprint = require_evidence_value(
        payload["canonical_path_fingerprint_sha256"],
        "canonical_path_fingerprint_sha256",
    )
    require_evidence_value(payload["path_completeness"], "path_completeness", value_kind="string")
    state = payload["outcome_state"]
    if not isinstance(state, str) or state != outcome_value["state"]:
        raise RecorderContractError("Outcome state and value evidence state must match.")
    bar_ids = payload["canonical_bar_record_ids"]
    bar_hashes = payload["canonical_bar_payload_sha256s"]
    if not isinstance(bar_ids, list) or not isinstance(bar_hashes, list):
        raise RecorderContractError("Canonical bar IDs and hashes must be ordered arrays.")
    if len(bar_ids) != len(bar_hashes):
        raise RecorderContractError("Canonical bar ID/hash arrays must have equal length.")
    for index, identity in enumerate(bar_ids):
        require_identity(
            identity,
            f"canonical_bar_record_ids[{index}]",
            kinds=frozenset({"MARKET_SNAPSHOT_ID"}),
        )
        require_sha256(bar_hashes[index], f"canonical_bar_payload_sha256s[{index}]")
    expected_series = outcome_series_binding_sha256(payload)
    if payload["canonical_series_fingerprint_sha256"] != expected_series:
        raise RecorderContractError("Outcome series fingerprint does not bind exact bar bytes.")
    if path_fingerprint["state"] == "PRESENT":
        require_sha256(
            path_fingerprint.get("value"),
            "canonical_path_fingerprint_sha256.value",
        )
        if path_fingerprint.get("value") != expected_series:
            raise RecorderContractError("Canonical path fingerprint does not bind exact bar bytes.")
    if state == "PRESENT":
        if payload["outcome_semantic"] in {"MFE", "MAE"}:
            raise RecorderContractError(
                "PRESENT MFE/MAE is not implemented by this bounded custody kernel."
            )
        if outcome_value["state"] != "PRESENT" or path_fingerprint["state"] != "PRESENT":
            raise RecorderContractError("PRESENT outcome requires present value and path evidence.")
    else:
        if outcome_value["state"] != state:
            raise RecorderContractError("Non-PRESENT outcome value must carry the same explicit state.")
        if bar_ids or bar_hashes or path_fingerprint["state"] == "PRESENT":
            raise RecorderContractError("Non-PRESENT outcome prohibits canonical bar/value path bytes.")
        if payload["outcome_time"].get("state") != state:
            raise RecorderContractError("Non-PRESENT outcome_time must carry the same explicit state.")
        if payload["outcome_semantic"] in {"MFE", "MAE"} and state not in {
            "UNAVAILABLE", "NOT_APPLICABLE", "NOT_OBSERVED", "PROVIDER_FAILED",
            "SESSION_TRUNCATED", "PARTIAL", "FAILED",
        }:
            raise RecorderContractError("MFE/MAE requires a reasoned non-PRESENT state.")
    for field in ("reference_price", "return_value", "mfe_value", "mae_value"):
        if field in payload:
            require_evidence_value(payload[field], field, value_kind="decimal")
    if "reference_price_market_snapshot_id" in payload:
        require_evidence_value(
            payload["reference_price_market_snapshot_id"],
            "reference_price_market_snapshot_id",
            value_kind="identity",
            identity_kinds=frozenset({"MARKET_SNAPSHOT_ID"}),
        )
    if "truncation_reason_code" in payload:
        require_evidence_value(payload["truncation_reason_code"], "truncation_reason_code", value_kind="string")
    for field, kinds in (
        ("provider_health_event_ids", frozenset({"PROVIDER_HEALTH_EVENT_ID"})),
        ("attempt_receipt_ids", None),
    ):
        if field in payload:
            values = payload[field]
            if not isinstance(values, list):
                raise RecorderContractError(f"{field} must be an array.")
            for index, identity in enumerate(values):
                require_identity(identity, f"{field}[{index}]", kinds=kinds)
    supplied_link = require_sha256(
        payload["linkage_receipt_sha256"], "linkage_receipt_sha256"
    )
    if outcome_linkage_sha256(payload) != supplied_link:
        raise RecorderContractError("Outcome linkage receipt does not bind exact payload links.")


def parse_outcome_attachment(raw: bytes) -> ValidatedOutcomeAttachment:
    try:
        value = strict_json_loads(raw)
    except CanonicalizationError as exc:
        raise RecorderContractError(str(exc)) from exc
    expected = {
        "schema_version",
        "record_type",
        "offline_reference_profile",
        "canonicalization_version",
        "hash_algorithm",
        "hash_unit",
        "previous_record_hash_target",
        "source_sequence_scope",
        "stream_id",
        "session_id",
        "source_owner",
        "source_event_id",
        "source_sequence",
        "previous_record_sha256",
        "observed_at",
        "authority",
        "execution_authority",
        "payload_sha256",
        "payload",
    }
    if set(value) != expected:
        raise RecorderContractError("Outcome attachment has missing or unknown fields.")
    if value["schema_version"] != SCHEMA_VERSION or value["record_type"] != OUTCOME_ATTACHMENT_CONTRACT:
        raise RecorderContractError("Unsupported outcome attachment lineage.")
    from .canonical import CANONICALIZATION_VERSION

    profile = {
        "offline_reference_profile": SCIENCE_OFFLINE_OUTCOME_PROFILE,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "hash_unit": HASH_UNIT,
        "previous_record_hash_target": PREVIOUS_HASH_TARGET,
        "source_sequence_scope": SOURCE_SEQUENCE_SCOPE,
    }
    for field, expected_value in profile.items():
        if value[field] != expected_value:
            raise RecorderContractError(f"Unsupported outcome reference profile: {field}.")
    if value["authority"] != AUTHORITY or value["execution_authority"] != EXECUTION_AUTHORITY:
        raise RecorderContractError("Outcome attachment exceeds research-only authority.")
    session_id = require_identity(
        value["session_id"], "session_id", kinds=frozenset({"SESSION_ID"})
    )
    sequence = value["source_sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise RecorderContractError("source_sequence must be a positive integer.")
    previous = value["previous_record_sha256"]
    if previous != GENESIS_SHA256:
        require_sha256(previous, "previous_record_sha256")
    parse_rfc3339(value["observed_at"], "observed_at")
    payload = value["payload"]
    if not isinstance(payload, Mapping):
        raise RecorderContractError("Outcome payload must be an object.")
    payload_sha = require_sha256(value["payload_sha256"], "payload_sha256")
    if sha256_hex(canonical_json_bytes(payload)) != payload_sha:
        raise RecorderContractError("Outcome payload SHA-256 does not match bytes.")
    validate_outcome_payload(payload)
    observed_at = parse_rfc3339(value["observed_at"], "observed_at")
    outcome_time = payload["outcome_time"]
    if outcome_time.get("state") == "PRESENT" and evidence_instant(outcome_time, "outcome_time") > observed_at:
        raise RecorderContractError("Outcome observed_at cannot precede the frozen outcome time.")
    if (
        payload["outcome_state"] in PROVIDER_DERIVED_TERMINAL_OUTCOME_STATES
        and observed_at < evidence_instant(payload["target_time"], "target_time")
    ):
        raise RecorderContractError(
            "Provider-derived terminal outcome cannot be observed before its exact target."
        )
    reject_prohibited_fields(value)
    return ValidatedOutcomeAttachment(
        raw_bytes=raw,
        raw_sha256=sha256_hex(raw),
        stream_id=_text(value, "stream_id"),
        session_id=session_id,
        source_owner=_text(value, "source_owner"),
        source_event_id=_text(value, "source_event_id"),
        source_sequence=sequence,
        previous_record_sha256=str(previous),
        observed_at=str(value["observed_at"]),
        payload_sha256=payload_sha,
        payload=payload,
    )


__all__ = [
    "OUTCOME_ATTACHMENT_CONTRACT",
    "SCIENCE_OFFLINE_OUTCOME_PROFILE",
    "ValidatedOutcomeAttachment",
    "outcome_linkage_sha256",
    "outcome_series_binding_sha256",
    "parse_outcome_attachment",
    "validate_outcome_payload",
]
