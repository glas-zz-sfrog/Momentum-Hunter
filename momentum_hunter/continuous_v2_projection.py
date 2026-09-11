"""One-way projections of committed Continuous source records onto canonical V2.

Broad-discovery rows and composition observations are distinct populations. A
composition observation describes the member/setup *at that evaluation*, never
a retrofit of its original Finviz observation. Original source bytes accompany
each projection in the producer checkpoint, not in the Science wire schema.
"""
from __future__ import annotations

import json
from decimal import Decimal

from momentum_hunter.broad_discovery import DiscoverySnapshot
from momentum_hunter.continuous_research_export import (
    evidence_present, evidence_unresolved, instrument_identity, producer_identity,
    time_evidence,
)
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousProducerRecord, CurrentMarketEvidence, validate_current_market_evidence, validate_producer_record,
)
from momentum_hunter.continuous_time_identity import parse_instant
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_v1, sha256_hex
from momentum_hunter.strategy_science_recorder.contract import (
    REPAIRED_EXPORT_SCHEMA_VERSION, validate_export_payload_profile,
)

OWNER = "continuous-runtime-v2-producer-v1"


def fingerprint(value):
    return sha256_hex(canonical_json_v1(value))


def identity(kind, value, namespace=OWNER):
    return producer_identity(kind, namespace, value)


def missing(reason="SOURCE_VALUE_NOT_RECORDED"):
    return evidence_unresolved(OWNER, reason_code=reason)


def present(value):
    return evidence_present(value, OWNER)


def clock(role, value, authority=OWNER):
    return time_evidence(role, value, authority)


def instrument(symbol):
    return instrument_identity(symbol=present(symbol), asset_type=missing(),
                               venue_or_exchange=missing(), authoritative_security_id=missing())


def number(value, integer=False):
    if value is None:
        return missing()
    if isinstance(value, bool):
        raise ValueError("Boolean is not a market number.")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or (integer and parsed != int(parsed)):
        raise ValueError("Source numeric value is not finite or integral.")
    return present(int(parsed) if integer else format(parsed, "f"))


def event(kind, key, payload):
    validate_export_payload_profile(kind, payload, export_schema_version=REPAIRED_EXPORT_SCHEMA_VERSION)
    return {"event_type": kind, "source_event_id": key, "payload": payload}


def observation(key, cycle, subject, symbol, observed, source_hash, *, member_id=None,
                facts=None, evaluated=False, reasons=(), ordinal=0):
    row = {"observation_id": identity("OBSERVATION_ID", key), "discovery_cycle_id": cycle,
           "source_row_ordinal": ordinal, "source_row_fingerprint_sha256": source_hash,
           "instrument_identity": instrument(symbol), "candidate_or_setup_identity": subject,
           "rank": missing("NO_PERSISTED_RANK"), "discovery_time": clock("DISCOVERY_TIME", observed),
           "candidate_facts": facts or {}, "materially_evaluated": evaluated,
           "rejection_or_gap_reasons": [{"code": value, "version": "1"} for value in reasons]}
    if member_id is not None:
        row["owner_member_id"] = present(member_id)
    return row


def cycle_event(key, rows, observed, received, policy, *, state="COMPLETE", source_cursor=None):
    cycle = {"discovery_cycle_id": identity("DISCOVERY_CYCLE_ID", key), "cycle_state": state,
             "query_or_policy_fingerprint_sha256": policy,
             "discovery_time": clock("DISCOVERY_TIME", observed),
             "provider_received_at": clock("PROVIDER_RECEIVED_AT", received),
             "returned_row_count": len(rows), "row_order_complete": present(True),
             "observation_ids_in_source_order": [row["observation_id"] for row in rows],
             "provider_health_event_ids": [], "zero_result": state == "ZERO_RESULT",
             "completeness": present(state)}
    if source_cursor is not None:
        cycle["source_cursor"] = present(source_cursor)
    return event("DISCOVERY_CYCLE", key, {"discovery_cycle": cycle, "observations": rows})


def discovery_events(payload):
    source = payload["sourceEvidence"]
    raw = source["snapshot"]
    snapshot = DiscoverySnapshot.from_dict(raw)
    key = "discovery:" + snapshot.snapshot_id
    cycle = identity("DISCOVERY_CYCLE_ID", key)
    # Discovery is the source receipt of a bounded result, not the earlier
    # pre-request evaluatedAt supplied by the live acquisition wrapper.
    observed = raw["receivedAt"]
    rows = []
    for ordinal, row in enumerate(raw["rows"]):
        row_key = fingerprint({"snapshotId": snapshot.snapshot_id, "rowId": row["rowId"],
                               "sourceRowOrdinal": row["sourceRowOrdinal"]})
        values = row["parsedValues"]
        facts = {target: number(values.get(field), target == "volume") for field, target in (
            ("price", "price"), ("volume", "volume"), ("relativeVolume", "rvol"),
            ("marketCap", "market_cap"), ("floatShares", "float"))}
        rows.append(observation("row:" + row_key, cycle,
                    identity("CANDIDATE_MEMBER", row_key, "continuous-discovery-row-occurrence-v1"),
                    row["symbol"], observed, row["fingerprint"], facts=facts,
                    evaluated=False, reasons=row["dispositionReasons"], ordinal=ordinal))
    if snapshot.failure_reason and not rows:
        state = "FAILED"
    elif snapshot.failure_reason or snapshot.truncation_reason or snapshot.unseen_row_count not in (0,):
        state = "PARTIAL"
    else:
        state = "COMPLETE" if rows else "ZERO_RESULT"
    result = [cycle_event(key, rows, observed, observed, snapshot.query_fingerprint,
                          state=state, source_cursor=snapshot.fingerprint)]
    if state in {"FAILED", "PARTIAL"}:
        result.append(health_event(key + ":health", "DISCOVERY", observed,
                                  "SOURCE_OUTAGE" if state == "FAILED" else "PARTIAL", state))
    return result


def health_event(key, stage, observed, event_class, reason):
    return event("PROVIDER_HEALTH", key, {"provider_health_event": {
        "provider_health_event_id": identity("PROVIDER_HEALTH_EVENT_ID", key),
        "interface_or_owner": "continuous-runtime:" + stage,
        "event_class": event_class, "event_state": "UNAVAILABLE" if event_class != "PARTIAL" else "PARTIAL",
        "reason_code": reason, "source_event_time": clock("SOURCE_EVENT_TIME", observed),
        # This is the runtime adapter's receipt of a result/failure, not a
        # claim that a failed provider supplied its own timestamp.
        "provider_received_at": clock("PROVIDER_RECEIVED_AT", observed),
        "affected_record_ids": [], "attempt_number": missing("ATTEMPT_NUMBER_NOT_EXPORTED"),
        "terminal": False, "secret_material_present": False}})


def _market_event(record, member, key, observation_id):
    evidence = CurrentMarketEvidence(**record["currentMarketEvidence"])
    validate_current_market_evidence(evidence, expected_symbol=member["symbol"])
    payload = json.loads(evidence.market_payload_json)
    quote = payload.get("quote", {})
    facts = {name: number(quote.get(name), name == "volume")
             for name in ("price", "bid", "ask", "mark", "volume")}
    if "price" not in quote:
        facts["price"] = number(quote.get("last"))
    return event("MARKET_FACT", key, {"market_snapshot": {
        "market_snapshot_id": identity("MARKET_SNAPSHOT_ID", key),
        "snapshot_kind": "DECISION_SNAPSHOT", "instrument_identity": instrument(member["symbol"]),
        "observation_id": present(observation_id), "decision_id": missing("DECISION_NOT_YET_PUBLISHED"),
        "outcome_series_id": missing("SCIENCE_OWNED_LATER_ATTACHMENT"),
        "source_event_time": clock("SOURCE_EVENT_TIME", evidence.provider_timestamp, evidence.source_identity),
        "provider_known_at": clock("PROVIDER_KNOWN_AT", evidence.provider_timestamp, evidence.source_identity),
        "provider_received_at": clock("PROVIDER_RECEIVED_AT", evidence.receipt_timestamp, evidence.source_identity),
        "market_facts": facts, "market_data_owner": evidence.source_identity,
        "source_market_fact_fingerprint_sha256": evidence.evidence_fingerprint}})


def _reference_level(plan, role, value, currency):
    if value is None or currency is None:
        return {**missing("SOURCE_LEVEL_MISSING" if value is None else "CURRENCY_AUTHORITY_UNAVAILABLE"),
                "level_role": role}
    return {**number(value), "level_role": role, "currency": currency,
            "reference_level_id": identity("REFERENCE_LEVEL_ID", plan["plan_id"] + ":" + role),
            "level_source_fingerprint_sha256": plan["fingerprint"]}


def composition_events(payload, runtime_fingerprint):
    if payload.get("payloadType") != "CONTINUOUS_NATURAL_COMPOSITION_CHAIN":
        raise ValueError("Composition must retain the canonical committed natural chain.")
    return _evaluation_events(payload["naturalSteps"], payload["request"]["opportunity_id"],
                              payload["request"]["symbol"], runtime_fingerprint)


def native_record_events(source, runtime_fingerprint):
    fields = dict(source)
    fields["blockers"] = tuple(fields["blockers"])
    native = ContinuousProducerRecord(**fields)
    validate_producer_record(native)
    # Recover the original validated record, not a rerun or a synthesized chain.
    return _evaluation_events([{"producerRecord": json.loads(native.payload_json),
        "producerRecordId": native.record_id, "producerRecordFingerprint": native.fingerprint}],
        native.member_id, native.symbol, runtime_fingerprint)


def _evaluation_events(steps, member_id, symbol, runtime_fingerprint):
    result = []
    for step in steps:
        record = step["producerRecord"]
        cycle = record["compositionCycle"]
        members = [m for m in cycle["member_results"] if m["universe_member_id"] == member_id]
        if len(members) != 1 or members[0]["symbol"] != symbol:
            raise ValueError("Committed member identity is missing or contradictory.")
        member = members[0]
        plan = member["intraday_plan"]
        setup = member["lifecycle_proposal"]
        setup_id = setup.get("setup_id") if setup else None
        if plan is not None and not setup_id:
            raise ValueError("Reference plan has no authoritative setup identity.")
        key = "evaluation:" + step["producerRecordId"]
        subject = identity("SETUP", setup_id) if setup_id else identity("CANDIDATE_MEMBER", member_id)
        cutoff = cycle["evidence_cutoff"]
        current = record["currentMarketEvidence"]
        for known in (current["receipt_timestamp"], record["historicalContext"]["evidence_cutoff"]):
            if parse_instant(known) > parse_instant(cutoff):
                raise ValueError("Native source evidence exceeds its decision cutoff.")
        # This is a separate, policy-owned member evaluation population. It
        # never substitutes a later setup into the earlier provider row.
        observation_key = key + ":observation"
        observed = observation(observation_key, identity("DISCOVERY_CYCLE_ID", key), subject,
                               member["symbol"], cutoff, step["producerRecordFingerprint"],
                               member_id=member_id, evaluated=True, reasons=member["blocker_reasons"])
        result.append(cycle_event(key, [observed], cutoff, current["receipt_timestamp"],
                                 cycle["composition_policy_fingerprint"],
                                 source_cursor="COMMITTED_MEMBER_EVALUATION:" + cycle["cycle_id"]))
        market_key = key + ":market:" + current["evidence_id"]
        market_event = _market_event(record, member, market_key, observed["observation_id"])
        result.append(market_event)
        state = "TRADEPLAN" if plan else ("BLOCKED" if member["blocker_reasons"] else "NO_PLAN")
        if "MISSED" in member["disposition"]:
            state = "MISSED"
        decision_id = identity("DECISION_ID", step["producerRecordId"])
        reference_id = identity("REFERENCE_PLAN_ID", key + ":reference:" + plan["plan_id"]) if plan else None
        decision = {
            "decision_id": decision_id, "observation_id": observed["observation_id"],
            "candidate_or_setup_identity": subject, "decision_state": state,
            "reason_codes": [{"code": member["disposition"], "version": "1"}],
            "decision_time": clock("DECISION_TIME", cutoff), "decision_cutoff": clock("DECISION_CUTOFF", cutoff),
            # This field references Science-normalized custody bytes, which an
            # Engine producer cannot know. Do not fabricate those hashes or ask
            # Science for them; source chronology is checked above and retained.
            "known_at_evidence_refs": [],
            "strategy_identity": missing("NO_EXPORTED_STRATEGY_IDENTITY"),
            "decision_policy_fingerprint_sha256": cycle["composition_policy_fingerprint"],
            "config_fingerprint_sha256": record["configurationFingerprint"],
            "runtime_fingerprint_sha256": runtime_fingerprint,
            "market_snapshot_id": present(identity("MARKET_SNAPSHOT_ID", market_key)),
            "tradeplan_id": present(identity("TRADEPLAN_ID", plan["plan_id"])) if plan else missing("NO_PLAN"),
            "reference_plan_id": present(reference_id) if plan else missing("NO_PLAN")}
        projection = {"decision_event": decision}
        if plan:
            quote = json.loads(current["market_payload_json"]).get("quote", {})
            currency = quote.get("currency")
            targets = plan["target_prices"]
            projection["reference_plan"] = {
                "reference_plan_id": reference_id,
                "tradeplan_id": identity("TRADEPLAN_ID", plan["plan_id"]), "decision_id": decision_id,
                "candidate_or_setup_identity": subject, "plan_owner": "continuous-tradeplan-producer",
                "plan_schema_version": str(plan["schema_version"]),
                "plan_source_fingerprint_sha256": plan["fingerprint"],
                "plan_created_at": clock("DECISION_TIME", plan["created_at"]),
                "entry": _reference_level(plan, "ENTRY", plan["planned_entry"], currency),
                "stop": _reference_level(plan, "STOP", plan["stop_price"], currency),
                "t1": _reference_level(plan, "T1", targets[0] if targets else None, currency),
                "t2": _reference_level(plan, "T2", targets[1] if len(targets) > 1 else None, currency)}
        result.append(event("DECISION_FACT", key + ":decision", projection))
    return result


def project(stage, source, observed, runtime_fingerprint):
    if stage == "DISCOVERY":
        return discovery_events(source)
    if stage == "COMPOSITION":
        return composition_events(source, runtime_fingerprint)
    if stage == "NATIVE_PRODUCER_RECORD":
        return native_record_events(source, runtime_fingerprint)
    if stage == "HEALTH":
        return [health_event(source["event_id"], source["stage"], source.get("source_observed_at", observed),
                             source["event_class"], source["reason"])]
    raise ValueError("Unsupported Continuous source event stage.")
