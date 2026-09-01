from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    CanonicalizationError,
    RecorderContractError,
    canonical_json_v1,
    owner_identity,
    parse_export_envelope_v1,
    recorder_identity,
    sha256_hex,
)
from momentum_hunter.strategy_science_recorder.canonical import strict_json_loads
from momentum_hunter.strategy_science_recorder.contract import (
    GENESIS_SHA256,
    HASH_ALGORITHM,
    HASH_UNIT,
    HORIZONS,
    PREDECESSOR_SCHEMA_VERSION,
    PREVIOUS_HASH_TARGET,
    SCIENCE_OFFLINE_EXPORT_PROFILE,
    SOURCE_SEQUENCE_SCOPE,
    TIME_NORMALIZATION_RULE,
    require_identity,
)
from momentum_hunter.strategy_science_recorder.outcomes import (
    OUTCOME_ATTACHMENT_CONTRACT,
    SCIENCE_OFFLINE_OUTCOME_PROFILE,
    outcome_linkage_sha256,
    outcome_series_binding_sha256,
)


SOURCE_ROOT_IDENTITY = "9" * 64
BASE_TIME = "2026-09-01T13:30:00Z"
DISCOVERY_TIME = "2026-09-01T13:31:00Z"
DECISION_CUTOFF = "2026-09-01T13:31:30Z"
DECISION_TIME = "2026-09-01T13:31:31Z"
BAR_TIME = "2026-09-01T13:37:00Z"


class FixedClock:
    def __init__(self, value: str = "2026-09-01T14:00:00Z") -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


def present(value: object, authority: str = "fixture-owner") -> dict[str, object]:
    return {
        "authority": authority,
        "reason_code": "PRESENT",
        "state": "PRESENT",
        "value": value,
    }


def absent(
    state: str = "NOT_APPLICABLE",
    reason: str = "NOT_APPLICABLE",
    authority: str = "fixture-owner",
) -> dict[str, object]:
    return {"authority": authority, "reason_code": reason, "state": state}


def time_evidence(role: str, value: str, authority: str = "fixture-owner") -> dict[str, object]:
    return {
        "authority": authority,
        "normalized_rfc3339": value,
        "normalization_rule_version": TIME_NORMALIZATION_RULE,
        "precision": "second",
        "raw_value": value,
        "reason_code": "PRESENT",
        "role": role,
        "state": "PRESENT",
        "timezone_or_offset": "Z",
    }


def identity(kind: str, owner_id: str) -> dict[str, object]:
    return owner_identity(kind, "fixture-owner", owner_id)


SESSION_ID = identity("SESSION_ID", "session-2026-09-01")
CYCLE_ID = identity("DISCOVERY_CYCLE_ID", "cycle-1")
OBSERVATION_ID = identity("OBSERVATION_ID", "observation-1")
OBSERVATION_ID_2 = identity("OBSERVATION_ID", "observation-2")
SETUP_ID = identity("SETUP", "setup-1")
DECISION_ID = identity("DECISION_ID", "decision-1")
TRADEPLAN_ID = identity("TRADEPLAN_ID", "tradeplan-1")
REFERENCE_PLAN_ID = identity("REFERENCE_PLAN_ID", "reference-plan-1")
MARKET_SNAPSHOT_ID = identity("MARKET_SNAPSHOT_ID", "bar-1")
DECISION_SNAPSHOT_ID = identity("MARKET_SNAPSHOT_ID", "decision-snapshot-1")
OUTCOME_SERIES_ID = identity("OUTCOME_SERIES_ID", "series-1")
OUTCOME_ID = identity("OUTCOME_OBSERVATION_ID", "outcome-1")
HEALTH_ID = identity("PROVIDER_HEALTH_EVENT_ID", "health-1")


def outcome_policy(*, eligibility_mode: str = "ALL_UNIQUE_INSTRUMENTS") -> dict[str, object]:
    policy: dict[str, object] = {
        "bar_interval_semantic": "CANONICAL_ONE_MINUTE_REGULAR_SESSION_V1",
        "eligibility_mode": eligibility_mode,
        "exchange_calendar_id_and_version": "XNYS-2026a",
        "frozen_before_session": True,
        "horizons": list(HORIZONS),
        "outcome_selection_hindsight": False,
        "policy_id": "fixture-all-unique",
        "policy_version": "1.0.0",
        "provider_owner_load_limit": present(100, "fixture-provider-owner"),
        "retry_and_finalization_cutoff": {
            "finalization_cutoff": "2026-09-01T21:00:00Z",
            "maximum_attempts": 3,
        },
        "source_priority": ["fixture-market-owner"],
    }
    policy["policy_sha256"] = sha256_hex(canonical_json_v1(policy))
    return policy


def start_payload(
    *,
    eligibility_mode: str = "ALL_UNIQUE_INSTRUMENTS",
    regular_session_close: str = "2026-09-01T20:00:00Z",
) -> dict[str, object]:
    return {
        "exchange_market_date": "2026-09-01",
        "manifest_phase": "START",
        "market_timezone": "America/New_York",
        "outcome_followup_policy": outcome_policy(eligibility_mode=eligibility_mode),
        "regular_session_close": regular_session_close,
        "regular_session_open": "2026-09-01T13:30:00Z",
        "session_id": SESSION_ID,
        "session_kind": "REGULAR_SESSION",
        "source_owner_namespace": "fixture-owner",
        "source_root_identity": SOURCE_ROOT_IDENTITY,
        "source_runtime_activation_id": "activation-1",
    }


def instrument(symbol: str = "AAA") -> dict[str, object]:
    material = {
        "asset_type": present("EQUITY"),
        "authoritative_security_id": present(f"security-{symbol}"),
        "symbol": present(symbol),
        "venue_or_exchange": present("XNYS"),
    }
    material["instrument_identity_fingerprint_sha256"] = sha256_hex(
        canonical_json_v1(material)
    )
    return material


def observation(
    observation_id: dict[str, object] = OBSERVATION_ID,
    *,
    ordinal: int = 0,
    symbol: str = "AAA",
) -> dict[str, object]:
    return {
        "candidate_facts": {
            "persisted_score": present("7.25"),
            "price": present("12.34"),
            "volume": present(123456),
        },
        "candidate_or_setup_identity": SETUP_ID,
        "discovery_cycle_id": CYCLE_ID,
        "discovery_time": time_evidence("DISCOVERY_TIME", DISCOVERY_TIME),
        "instrument_identity": instrument(symbol),
        "materially_evaluated": True,
        "observation_id": observation_id,
        "rank": present(ordinal + 1),
        "rejection_or_gap_reasons": [],
        "source_row_fingerprint_sha256": sha256_hex(
            canonical_json_v1({"ordinal": ordinal, "symbol": symbol})
        ),
        "source_row_ordinal": ordinal,
    }


def discovery_payload(
    observations: list[dict[str, object]] | None = None,
    *,
    state: str = "COMPLETE",
) -> dict[str, object]:
    rows = [observation()] if observations is None else observations
    cycle = {
        "completeness": present("COMPLETE" if state == "COMPLETE" else state),
        "cycle_state": state,
        "discovery_cycle_id": CYCLE_ID,
        "discovery_time": time_evidence("DISCOVERY_TIME", DISCOVERY_TIME),
        "observation_ids_in_source_order": [row["observation_id"] for row in rows],
        "provider_health_event_ids": [],
        "provider_received_at": time_evidence("PROVIDER_RECEIVED_AT", DISCOVERY_TIME),
        "query_or_policy_fingerprint_sha256": "1" * 64,
        "returned_row_count": len(rows),
        "row_order_complete": present(True),
        "zero_result": state == "ZERO_RESULT",
    }
    return {"discovery_cycle": cycle, "observations": rows}


def reference_level(role: str, value: str) -> dict[str, object]:
    level = present(value)
    level.update(
        {
            "currency": "USD",
            "level_role": role,
            "level_source_fingerprint_sha256": sha256_hex(
                canonical_json_v1({"role": role, "value": value})
            ),
            "reference_level_id": identity("REFERENCE_LEVEL_ID", f"level-{role}"),
        }
    )
    return level


def decision_payload(eligibility_sha256: str) -> dict[str, object]:
    plan = {
        "candidate_or_setup_identity": SETUP_ID,
        "decision_id": DECISION_ID,
        "entry": reference_level("ENTRY", "12.40"),
        "plan_created_at": time_evidence("DECISION_TIME", DECISION_CUTOFF),
        "plan_owner": "fixture-owner",
        "plan_schema_version": "1.0.0",
        "plan_source_fingerprint_sha256": "2" * 64,
        "reference_plan_id": REFERENCE_PLAN_ID,
        "stop": reference_level("STOP", "11.90"),
        "t1": reference_level("T1", "13.00"),
        "t2": reference_level("T2", "13.60"),
        "tradeplan_id": TRADEPLAN_ID,
    }
    decision = {
        "candidate_or_setup_identity": SETUP_ID,
        "config_fingerprint_sha256": "3" * 64,
        "decision_cutoff": time_evidence("DECISION_CUTOFF", DECISION_CUTOFF),
        "decision_id": DECISION_ID,
        "decision_policy_fingerprint_sha256": "4" * 64,
        "decision_state": "TRADEPLAN",
        "decision_time": time_evidence("DECISION_TIME", DECISION_TIME),
        "known_at_evidence_refs": [],
        "market_snapshot_id": absent(reason="NO_CONTEMPORANEOUS_SNAPSHOT"),
        "observation_id": OBSERVATION_ID,
        "outcome_eligibility_commitment_sha256": eligibility_sha256,
        "reason_codes": [{"code": "TRADEPLAN", "version": "1"}],
        "reference_plan_id": present(REFERENCE_PLAN_ID),
        "runtime_fingerprint_sha256": "5" * 64,
        "strategy_identity": present("fixture-strategy-v1"),
        "tradeplan_id": present(TRADEPLAN_ID),
    }
    return {"decision_event": decision, "reference_plan": plan}


def market_bar_payload(
    *,
    market_snapshot_id: dict[str, object] = MARKET_SNAPSHOT_ID,
    outcome_series_id: dict[str, object] = OUTCOME_SERIES_ID,
    symbol: str = "AAA",
    bar_interval_start: str = "2026-09-01T13:36:00Z",
    bar_interval_end: str = BAR_TIME,
) -> dict[str, object]:
    return {
        "market_snapshot": {
            "decision_id": absent(),
            "instrument_identity": instrument(symbol),
            "market_data_owner": "fixture-market-owner",
            "market_facts": {
                "bar_close": present("12.80"),
                "bar_complete": present(True),
                "bar_high": present("12.90"),
                    "bar_interval_end": time_evidence("OUTCOME_TIME", bar_interval_end),
                    "bar_interval_start": time_evidence(
                    "SOURCE_EVENT_TIME", bar_interval_start
                ),
                "bar_low": present("12.60"),
                "bar_open": present("12.65"),
                "bar_volume": present(12000),
            },
            "market_snapshot_id": market_snapshot_id,
            "observation_id": absent(),
            "outcome_series_id": present(outcome_series_id),
            "provider_known_at": time_evidence("PROVIDER_KNOWN_AT", bar_interval_end),
            "provider_received_at": time_evidence("PROVIDER_RECEIVED_AT", bar_interval_end),
            "snapshot_kind": "CANONICAL_MINUTE_BAR",
            "source_event_time": time_evidence("SOURCE_EVENT_TIME", bar_interval_end),
            "source_market_fact_fingerprint_sha256": "6" * 64,
        }
    }


def decision_snapshot_payload(
    *,
    provider_known_at: str = "2026-09-01T13:31:20Z",
) -> dict[str, object]:
    return {
        "market_snapshot": {
            "decision_id": absent(),
            "instrument_identity": instrument(),
            "market_data_owner": "fixture-market-owner",
            "market_facts": {"price": present("12.35")},
            "market_snapshot_id": DECISION_SNAPSHOT_ID,
            "observation_id": present(OBSERVATION_ID),
            "outcome_series_id": absent(),
            "provider_known_at": time_evidence("PROVIDER_KNOWN_AT", provider_known_at),
            "provider_received_at": time_evidence(
                "PROVIDER_RECEIVED_AT", provider_known_at
            ),
            "snapshot_kind": "DECISION_SNAPSHOT",
            "source_event_time": time_evidence(
                "SOURCE_EVENT_TIME", "2026-09-01T13:31:15Z"
            ),
            "source_market_fact_fingerprint_sha256": "7" * 64,
        }
    }


def health_payload(
    *,
    event_class: str = "SOURCE_OUTAGE",
    terminal: bool = False,
    health_id: dict[str, object] = HEALTH_ID,
) -> dict[str, object]:
    return {
        "provider_health_event": {
            "affected_record_ids": [OBSERVATION_ID],
            "attempt_number": present(1),
            "event_class": event_class,
            "event_state": "UNAVAILABLE",
            "interface_or_owner": "fixture-owner",
            "provider_health_event_id": health_id,
            "provider_received_at": time_evidence("PROVIDER_RECEIVED_AT", BAR_TIME),
            "reason_code": "SOURCE_OUTAGE",
            "secret_material_present": False,
            "source_event_time": time_evidence("SOURCE_EVENT_TIME", BAR_TIME),
            "terminal": terminal,
        }
    }


def export_envelope(
    event_type: str,
    payload: dict[str, object],
    *,
    stream_id: str,
    event_id: str,
    sequence: int = 1,
    previous: str = GENESIS_SHA256,
    session_id: dict[str, object] = SESSION_ID,
) -> bytes:
    event_time = BASE_TIME
    effective_known_at = BASE_TIME
    emitted_at = BASE_TIME
    if event_type == "DISCOVERY_CYCLE":
        cycle = payload["discovery_cycle"]
        event_time = cycle["discovery_time"]["normalized_rfc3339"]
        effective_known_at = cycle["provider_received_at"]["normalized_rfc3339"]
        emitted_at = effective_known_at
    elif event_type == "DECISION_FACT":
        decision = payload["decision_event"]
        event_time = decision["decision_time"]["normalized_rfc3339"]
        effective_known_at = decision["decision_cutoff"]["normalized_rfc3339"]
        emitted_at = event_time
    elif event_type == "MARKET_FACT":
        market = payload["market_snapshot"]
        event_time = market["source_event_time"]["normalized_rfc3339"]
        known = market["provider_known_at"]
        effective_known_at = (
            known["normalized_rfc3339"]
            if known["state"] == "PRESENT"
            else market["provider_received_at"]["normalized_rfc3339"]
        )
        emitted_at = market["provider_received_at"]["normalized_rfc3339"]
    elif event_type == "PROVIDER_HEALTH":
        health = payload["provider_health_event"]
        event_time = health["source_event_time"]["normalized_rfc3339"]
        effective_known_at = health["provider_received_at"]["normalized_rfc3339"]
        emitted_at = effective_known_at
    elif event_type == "SESSION_MANIFEST" and payload.get("manifest_phase") == "FINAL":
        event_time = str(payload["closed_at"])
        effective_known_at = event_time
        emitted_at = event_time
    envelope = {
        "authority": "RESEARCH_ONLY",
        "canonicalization_version": "ARGUS_CANONICAL_JSON_V1",
        "effective_known_at": effective_known_at,
        "emitted_at": emitted_at,
        "event_time": event_time,
        "event_type": event_type,
        "execution_authority": "NONE",
        "hash_algorithm": HASH_ALGORITHM,
        "hash_unit": HASH_UNIT,
        "offline_reference_profile": SCIENCE_OFFLINE_EXPORT_PROFILE,
        "payload": payload,
        "payload_sha256": sha256_hex(canonical_json_v1(payload)),
        "previous_record_hash_target": PREVIOUS_HASH_TARGET,
        "previous_record_sha256": previous,
        "schema_version": "1.0.0",
        "session_id": session_id,
        "source_contract": "ResearchExportEnvelopeV1",
        "source_contract_version": PREDECESSOR_SCHEMA_VERSION,
        "source_event_fingerprint_sha256": sha256_hex(
            canonical_json_v1({"event_id": event_id, "owner": "fixture-owner"})
        ),
        "source_event_id": event_id,
        "source_interface_identity": "fixture-export-interface-v1",
        "source_owner_identity": "fixture-producing-owner",
        "source_sequence": sequence,
        "source_sequence_scope": SOURCE_SEQUENCE_SCOPE,
        "stream_id": stream_id,
    }
    return canonical_json_v1(envelope)


def start_envelope(**kwargs: object) -> bytes:
    return export_envelope(
        "SESSION_MANIFEST",
        start_payload(**kwargs),
        stream_id="session-stream",
        event_id="session-start",
    )


def source_final_envelope(
    recorder: object,
    start_raw: bytes,
    *,
    source_gap_count: int = 0,
    pending_source_events: int = 0,
    conflict_count: int = 0,
    closed_at: str = "2026-09-01T21:01:00Z",
) -> bytes:
    partition = recorder._locate_partition(SESSION_ID)
    heads, counts = recorder._source_stream_summary(partition)
    payload = {
        "close_reason": "FIXTURE_SESSION_COMPLETE",
        "closed_at": closed_at,
        "conflict_count": conflict_count,
        "manifest_phase": "FINAL",
        "pending_source_events": pending_source_events,
        "session_id": SESSION_ID,
        "source_event_type_counts_before_final": counts,
        "source_gap_count": source_gap_count,
        "source_root_identity": SOURCE_ROOT_IDENTITY,
        "source_stream_heads_before_final": heads,
    }
    return export_envelope(
        "SESSION_MANIFEST",
        payload,
        stream_id="session-stream",
        event_id="session-final",
        sequence=2,
        previous=sha256_hex(start_raw),
    )


def outcome_attachment(
    payload: dict[str, object],
    *,
    event_id: str = "outcome-attachment-1",
    sequence: int = 1,
    previous: str = GENESIS_SHA256,
    observed_at: str = "2026-09-01T14:01:00Z",
) -> bytes:
    envelope = {
        "authority": "RESEARCH_ONLY",
        "canonicalization_version": "ARGUS_CANONICAL_JSON_V1",
        "execution_authority": "NONE",
        "hash_algorithm": HASH_ALGORITHM,
        "hash_unit": HASH_UNIT,
        "observed_at": observed_at,
        "offline_reference_profile": SCIENCE_OFFLINE_OUTCOME_PROFILE,
        "payload": payload,
        "payload_sha256": sha256_hex(canonical_json_v1(payload)),
        "previous_record_hash_target": PREVIOUS_HASH_TARGET,
        "previous_record_sha256": previous,
        "record_type": OUTCOME_ATTACHMENT_CONTRACT,
        "schema_version": "1.0.0",
        "session_id": SESSION_ID,
        "source_event_id": event_id,
        "source_owner": "fixture-outcome-owner",
        "source_sequence": sequence,
        "source_sequence_scope": SOURCE_SEQUENCE_SCOPE,
        "stream_id": "outcome-stream",
    }
    return canonical_json_v1(envelope)


def stored_records(root: Path, record_type: str) -> list[tuple[Path, dict[str, object], bytes]]:
    results = []
    for path in root.rglob("*.payload.json"):
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get("record_type") == record_type:
            results.append((path, value, raw))
    return results


def valid_outcome_payload(root: Path) -> dict[str, object]:
    decision_bytes = stored_records(root, "decision-event")[0][2]
    bar_bytes = stored_records(root, "market-snapshot")[0][2]
    observation_record = stored_records(root, "candidate-observation")[0][1]
    eligibility_sha = observation_record["outcome_eligibility"][
        "commitment_payload_sha256"
    ]
    payload: dict[str, object] = {
        "candidate_or_setup_identity": SETUP_ID,
        "canonical_bar_payload_sha256s": [sha256_hex(bar_bytes)],
        "canonical_bar_record_ids": [MARKET_SNAPSHOT_ID],
        "canonical_path_fingerprint_sha256": present("0" * 64),
        "canonical_series_fingerprint_sha256": "0" * 64,
        "decision_id": DECISION_ID,
        "decision_payload_sha256": sha256_hex(decision_bytes),
        "eligibility_commitment_sha256": eligibility_sha,
        "linkage_receipt_sha256": "0" * 64,
        "observation_id": OBSERVATION_ID,
        "outcome_observation_id": OUTCOME_ID,
        "outcome_semantic": "PLUS_5M",
        "outcome_semantic_version": "1.0.0",
        "outcome_series_id": OUTCOME_SERIES_ID,
        "outcome_state": "PRESENT",
        "outcome_time": time_evidence("OUTCOME_TIME", BAR_TIME),
        "outcome_value": present("12.80"),
        "path_completeness": present("COMPLETE"),
        "target_time": time_evidence("OUTCOME_TIME", "2026-09-01T13:36:31Z"),
        "transform_version": "fixture-transform-v1",
    }
    series_sha = outcome_series_binding_sha256(payload)
    payload["canonical_series_fingerprint_sha256"] = series_sha
    payload["canonical_path_fingerprint_sha256"] = present(series_sha)
    payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
    return payload


class RecorderContractTests(unittest.TestCase):
    def test_golden_canonical_utf8_and_identity_are_stable(self) -> None:
        value = {"z": ["é", "12.30"], "a": {"b": 2, "a": True}}
        self.assertEqual(
            b'{"a":{"a":true,"b":2},"z":["\xc3\xa9","12.30"]}\n',
            canonical_json_v1(value),
        )
        self.assertEqual(owner_identity("SESSION_ID", "fixture-owner", "session-2026-09-01"), SESSION_ID)
        self.assertEqual(64, len(SESSION_ID["recorder_id"].rsplit(":", 1)[1]))

    def test_strict_json_rejects_duplicate_null_float_nonfinite_and_noncanonical(self) -> None:
        invalid = (
            b'{"a":1,"a":2}\n',
            b'{"a":null}\n',
            b'{"a":1.2}\n',
            b'{"a":NaN}\n',
            b'{"b":1, "a":2}\n',
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(CanonicalizationError):
                    strict_json_loads(raw)

    def test_export_parser_binds_exact_offline_profile_and_payload_hash(self) -> None:
        raw = start_envelope()
        parsed = parse_export_envelope_v1(raw)
        self.assertEqual("SESSION_MANIFEST", parsed.event_type)
        self.assertEqual(sha256_hex(raw), parsed.raw_sha256)
        self.assertEqual("1.0.0-proposal", parsed.source_contract_version)

        for field in (
            "canonicalization_version",
            "hash_unit",
            "previous_record_hash_target",
            "source_sequence_scope",
        ):
            value = json.loads(raw)
            value[field] = "WRONG"
            with self.subTest(field=field), self.assertRaises(RecorderContractError):
                parse_export_envelope_v1(canonical_json_v1(value))

    def test_unknown_major_authority_and_capability_fields_fail_closed(self) -> None:
        cases = []
        base = json.loads(start_envelope())
        changed = dict(base)
        changed["schema_version"] = "2.0.0"
        cases.append(changed)
        changed = dict(base)
        changed["execution_authority"] = "PAPER"
        cases.append(changed)
        changed = dict(base)
        payload = dict(changed["payload"])
        payload["account_number"] = "forbidden"
        changed["payload"] = payload
        changed["payload_sha256"] = sha256_hex(canonical_json_v1(payload))
        cases.append(changed)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(RecorderContractError):
                parse_export_envelope_v1(canonical_json_v1(value))

    def test_fixed_bucket_policy_is_explicitly_unqualified(self) -> None:
        with self.assertRaises(RecorderContractError):
            parse_export_envelope_v1(start_envelope(eligibility_mode="FIXED_HASH_BUCKET"))

    def test_recorder_allocated_identity_has_independent_fixed_golden_digests(self) -> None:
        allocated = recorder_identity(
            "OBSERVATION_ID",
            {"session": "session-1", "source_sequence": 1, "source_row_ordinal": 0},
        )
        self.assertEqual(
            "c988e626ce65ca216264a4f25485c99483f6fc379910266f596132e87ddabe02",
            allocated["logical_key_fingerprint_sha256"],
        )
        self.assertEqual(
            "ar1:observation-id:a8df60854e39c1a07e2f8eaf7843786b0fdfc25707d83c836f14b3dfdef6af37",
            allocated["recorder_id"],
        )
        self.assertEqual(
            allocated,
            require_identity(
                allocated,
                "allocated",
                kinds=frozenset({"OBSERVATION_ID"}),
                allow_recorder_allocated=True,
            ),
        )
        counterfeit = dict(allocated)
        counterfeit["logical_key"] = dict(allocated["logical_key"], source_sequence=2)
        with self.assertRaises(RecorderContractError):
            require_identity(
                counterfeit, "counterfeit", allow_recorder_allocated=True
            )

    def test_external_start_parser_rejects_caller_allocated_session_identities(self) -> None:
        logical_keys = (
            {"symbol": "AAA"},
            {"futureReturnAfterClose": "9.99"},
            {"accountBalance": "100000"},
            {"note": "Bearer sk-proj-example"},
        )
        for ordinal, logical_key in enumerate(logical_keys, start=1):
            allocated = recorder_identity("SESSION_ID", logical_key)
            payload = start_payload()
            payload["session_id"] = allocated
            raw = export_envelope(
                "SESSION_MANIFEST",
                payload,
                stream_id="session-stream",
                event_id=f"caller-allocated-session-{ordinal}",
                session_id=allocated,
            )
            with self.subTest(logical_key=logical_key), self.assertRaises(
                RecorderContractError
            ):
                parse_export_envelope_v1(raw)

        parsed = parse_export_envelope_v1(start_envelope())
        self.assertEqual("OWNER_WRAPPED", parsed.session_id["allocation_mode"])

    def test_closed_nested_schemas_and_normalized_forbidden_names_fail_closed(self) -> None:
        cases: list[dict[str, object]] = []
        for forbidden in ("accountNumber", "apiKey", "orderId", "executionEndpoint"):
            value = json.loads(export_envelope(
                "DISCOVERY_CYCLE", discovery_payload(),
                stream_id="discovery-stream", event_id=f"forbidden-{forbidden}",
            ))
            value["payload"]["observations"][0][forbidden] = "forbidden"
            value["payload_sha256"] = sha256_hex(canonical_json_v1(value["payload"]))
            cases.append(value)
        unknown = json.loads(export_envelope(
            "DISCOVERY_CYCLE", discovery_payload(),
            stream_id="discovery-stream", event_id="unknown-future",
        ))
        unknown["payload"]["observations"][0]["candidate_facts"][
            "future_return_after_close"
        ] = present("9.99")
        unknown["payload_sha256"] = sha256_hex(canonical_json_v1(unknown["payload"]))
        cases.append(unknown)
        bad_integer = json.loads(export_envelope(
            "DISCOVERY_CYCLE", discovery_payload(),
            stream_id="discovery-stream", event_id="bool-volume",
        ))
        bad_integer["payload"]["observations"][0]["candidate_facts"]["volume"]["value"] = True
        bad_integer["payload_sha256"] = sha256_hex(canonical_json_v1(bad_integer["payload"]))
        cases.append(bad_integer)
        closed_detail_probes = {
            "balance": "100.00",
            "buyingPower": "100.00",
            "moneyTransfer": {"amount": "1.00"},
            "execution": {"side": "BUY"},
            "accountBalance": "100.00",
            "portfolioId": "portfolio-1",
            "note": "Bearer sk-proj-FAKE-NOT-A-CREDENTIAL",
        }
        for field, nested_value in closed_detail_probes.items():
            value = json.loads(export_envelope(
                "DISCOVERY_CYCLE", discovery_payload(),
                stream_id="discovery-stream", event_id=f"closed-detail-{field}",
            ))
            value["payload"]["observations"][0]["candidate_facts"]["price"][
                "detail"
            ] = {field: nested_value}
            value["payload_sha256"] = sha256_hex(canonical_json_v1(value["payload"]))
            cases.append(value)
        open_provenance = json.loads(export_envelope(
            "DECISION_FACT", decision_payload("a" * 64),
            stream_id="decision-stream", event_id="open-provenance-detail",
        ))
        open_provenance["payload"]["reference_plan"]["provenance_detail"] = {
            "note": "Bearer sk-proj-FAKE-NOT-A-CREDENTIAL"
        }
        open_provenance["payload_sha256"] = sha256_hex(
            canonical_json_v1(open_provenance["payload"])
        )
        cases.append(open_provenance)
        for value in cases:
            with self.subTest(event=value["source_event_id"]), self.assertRaises(RecorderContractError):
                parse_export_envelope_v1(canonical_json_v1(value))

    def test_time_identity_profile_and_envelope_chronology_fail_closed(self) -> None:
        base = json.loads(export_envelope(
            "DISCOVERY_CYCLE", discovery_payload(),
            stream_id="discovery-stream", event_id="time-probe",
        ))
        cases: list[dict[str, object]] = []
        missing_rule = json.loads(canonical_json_v1(base))
        del missing_rule["payload"]["discovery_cycle"]["discovery_time"][
            "normalization_rule_version"
        ]
        missing_rule["payload_sha256"] = sha256_hex(canonical_json_v1(missing_rule["payload"]))
        cases.append(missing_rule)
        raw_mismatch = json.loads(canonical_json_v1(base))
        raw_mismatch["payload"]["discovery_cycle"]["discovery_time"]["raw_value"] = BASE_TIME
        raw_mismatch["payload_sha256"] = sha256_hex(canonical_json_v1(raw_mismatch["payload"]))
        cases.append(raw_mismatch)
        wrong_offset = json.loads(canonical_json_v1(base))
        wrong_offset["payload"]["discovery_cycle"]["discovery_time"]["timezone_or_offset"] = "+00:00"
        wrong_offset["payload_sha256"] = sha256_hex(canonical_json_v1(wrong_offset["payload"]))
        cases.append(wrong_offset)
        future_clock = json.loads(canonical_json_v1(base))
        future_clock["emitted_at"] = BASE_TIME
        cases.append(future_clock)
        for value in cases:
            with self.subTest(value=value), self.assertRaises((RecorderContractError, CanonicalizationError)):
                parse_export_envelope_v1(canonical_json_v1(value))

    def test_instrument_fingerprint_binds_all_optional_and_required_identity_bytes(self) -> None:
        payload = discovery_payload()
        payload["observations"][0]["instrument_identity"]["currency"] = present("USD")
        material = dict(payload["observations"][0]["instrument_identity"])
        material.pop("instrument_identity_fingerprint_sha256")
        payload["observations"][0]["instrument_identity"][
            "instrument_identity_fingerprint_sha256"
        ] = sha256_hex(canonical_json_v1(material))
        raw = export_envelope(
            "DISCOVERY_CYCLE", payload,
            stream_id="discovery-stream", event_id="optional-instrument",
        )
        parse_export_envelope_v1(raw)
        changed = json.loads(raw)
        changed["payload"]["observations"][0]["instrument_identity"]["currency"]["value"] = "CAD"
        changed["payload_sha256"] = sha256_hex(canonical_json_v1(changed["payload"]))
        with self.assertRaises(RecorderContractError):
            parse_export_envelope_v1(canonical_json_v1(changed))


if __name__ == "__main__":
    unittest.main()
