from __future__ import annotations

"""Build deterministic offline review packets from terminal Shadow evidence.

This module is deliberately downstream of the Shadow runtime. It reads explicit
files, validates their identities, and writes new review artifacts. It has no
provider, broker, service, Engine Host, scheduler, or Codex integration.
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from momentum_hunter.shadow_opening import shadow_handoff_findings
from momentum_hunter.shadow_trading import (
    TERMINAL_TRADE_STATES,
    ShadowSampleMetadata,
    ShadowSelectionPolicy,
    ShadowStateError,
    ShadowTrade,
    audit_shadow_trade,
    shadow_identity_linkage_status,
    shadow_sample_metadata_findings,
    shadow_state_from_dict,
    shadow_trade_direction,
    validate_shadow_selection_policy,
)


PACKET_SCHEMA_VERSION = 1
NO_TRADE_TERMINAL_STATUSES = frozenset(
    {
        "NO_ELIGIBLE_CANDIDATE",
        "REPORT_NOT_PROSPECTIVE",
        "SOURCE_CAPTURE_ALREADY_PROCESSED",
    }
)
FIELD_CLASSIFICATIONS = frozenset(
    {"STORED_FACT", "DETERMINISTIC_DERIVATION", "MISSING", "REVIEW_QUESTION"}
)
_SAFE_EVENT_ID = re.compile(r"[^A-Za-z0-9._-]+")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?i)(client[_-]?secret|access[_-]?token|refresh[_-]?token|password|mfa|"
    r"authorization|account[_-]?(number|hash)|encrypted[_-]?account)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]{12,}|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{12,}|"
    r"AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.)"
)


class TerminalReviewPacketError(RuntimeError):
    """A fail-closed packet validation or write error."""


@dataclass(frozen=True)
class TerminalReviewPacketRequest:
    event_id: str
    output_dir: Path
    state_path: Path
    decision_cycles_path: Path
    handoff_path: Path
    report_path: Path
    activation_path: Path
    selection_policy_path: Path


@dataclass(frozen=True)
class TerminalReviewPacketResult:
    packet_id: str
    packet_fingerprint: str
    event_id: str
    event_kind: str
    json_path: Path
    markdown_path: Path
    duplicate: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "EXACT_DUPLICATE" if self.duplicate else "CREATED",
            "packetId": self.packet_id,
            "packetFingerprint": self.packet_fingerprint,
            "eventId": self.event_id,
            "eventKind": self.event_kind,
            "jsonPath": str(self.json_path),
            "markdownPath": str(self.markdown_path),
            "networkUsed": False,
            "sourceMutation": False,
        }


@dataclass(frozen=True)
class _InputDocument:
    role: str
    path: Path
    raw: bytes
    sha256: str
    payload: Any


def stored(value: Any, source: str) -> dict[str, Any]:
    return {"classification": "STORED_FACT", "source": source, "value": value}


def derived(
    value: Any,
    *,
    inputs: Sequence[str],
    formula: str,
    rounding: str = "none",
    missing_behavior: str = "MISSING",
) -> dict[str, Any]:
    return {
        "classification": "DETERMINISTIC_DERIVATION",
        "value": value,
        "inputs": list(inputs),
        "formula": formula,
        "rounding": rounding,
        "missingBehavior": missing_behavior,
    }


def missing(reason: str) -> dict[str, Any]:
    return {"classification": "MISSING", "reason": reason, "value": None}


def review_question(text: str) -> dict[str, Any]:
    return {"classification": "REVIEW_QUESTION", "question": text, "value": None}


def build_terminal_review_packet(
    request: TerminalReviewPacketRequest,
    *,
    known_sensitive_values: Sequence[str] = (),
) -> TerminalReviewPacketResult:
    """Validate one terminal event chain and write its immutable review packet."""

    if not request.event_id.strip():
        raise TerminalReviewPacketError("A non-empty event ID is required.")
    documents = _read_documents(request)
    initial_hashes = {document.path: document.sha256 for document in documents}
    by_role = {document.role: document for document in documents}

    state = _load_state(by_role["shadow_state"].payload)
    cycles = _load_cycles(by_role["decision_cycles"].payload)
    handoff = _require_object(by_role["handoff"].payload, "handoff")
    activation = _load_activation(by_role["sample_activation"].payload)
    selection_policy = _load_selection_policy(by_role["selection_policy"].payload)

    event = _resolve_event(request.event_id, state.trades, cycles)
    trade = event.get("trade")
    cycle = event["cycle"]
    _validate_report_identity(by_role["source_report"], trade, cycle, handoff)
    _validate_event_chain(trade, cycle, handoff, activation, selection_policy, state.trades)

    sections = (
        _trade_sections(trade, cycle)
        if isinstance(trade, ShadowTrade)
        else _no_trade_sections(cycle)
    )
    metadata = _require_object(activation.get("sample_metadata"), "sample metadata")
    source_identity = {
        "eventId": request.event_id,
        "eventKind": event["kind"],
        "decisionCycleId": str(cycle.get("cycle_id", "")),
        "shadowTradeId": trade.shadow_trade_id if isinstance(trade, ShadowTrade) else None,
        "captureId": str(handoff.get("captureId", "")),
        "handoffCommandId": str(handoff.get("commandId", "")),
        "simulationCommandId": (
            trade.simulation_command_id if isinstance(trade, ShadowTrade) else None
        ),
        "sampleVersion": str(metadata.get("sample_version", "")),
        "strategyConfigurationFingerprint": str(
            metadata.get("strategy_configuration_fingerprint", "")
        ),
        "fillModelVersion": str(metadata.get("fill_model_version", "")),
        "evidenceSchemaVersion": metadata.get("evidence_schema_version"),
        "selectionPolicyFingerprint": str(
            selection_policy.get("selection_policy_fingerprint", "")
        ),
        "reportSha256": by_role["source_report"].sha256,
    }
    input_files = [
        {
            "role": document.role,
            "filename": document.path.name,
            "sha256": document.sha256,
            "bytes": len(document.raw),
        }
        for document in sorted(documents, key=lambda item: item.role)
    ]
    creation_timestamp = _terminal_timestamp(trade, cycle, handoff)
    semantic_fingerprint = _sha256_json(
        {
            "schemaVersion": PACKET_SCHEMA_VERSION,
            "sourceEventIdentity": source_identity,
            "creationTimestamp": creation_timestamp,
            "inputFiles": input_files,
            "sections": sections,
        }
    )
    packet_id = f"terminal-review-{semantic_fingerprint[:20]}"
    packet = {
        "schemaVersion": PACKET_SCHEMA_VERSION,
        "packetId": packet_id,
        "packetFingerprint": semantic_fingerprint,
        "sourceEventIdentity": source_identity,
        "creationTimestamp": creation_timestamp,
        "inputFiles": input_files,
        "derivedValueDefinitions": _derived_definitions(),
        "sections": sections,
        "boundaries": {
            "offline": True,
            "readOnlySources": True,
            "networkUsed": False,
            "providerCalls": False,
            "brokerCalls": False,
            "serviceCalls": False,
            "engineHostCalls": False,
            "codexInvoked": False,
            "orderTransmission": "UNAVAILABLE",
        },
    }
    _validate_packet_shape(packet)
    json_bytes = _canonical_json_bytes(packet)
    markdown_bytes = render_terminal_review_markdown(packet).encode("utf-8")
    verify_packet_security(
        json_bytes + b"\n" + markdown_bytes,
        known_sensitive_values=known_sensitive_values,
    )
    _assert_sources_unchanged(initial_hashes)

    safe_event_id = _SAFE_EVENT_ID.sub("-", request.event_id).strip("-._")
    if not safe_event_id:
        raise TerminalReviewPacketError("The event ID cannot form a safe output filename.")
    output_dir = request.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"terminal-review-{safe_event_id}.json"
    markdown_path = output_dir / f"terminal-review-{safe_event_id}.md"
    duplicate = _write_pair_once(json_path, json_bytes, markdown_path, markdown_bytes)
    try:
        _assert_sources_unchanged(initial_hashes)
    except TerminalReviewPacketError:
        if not duplicate:
            _remove_new_output_pair(json_path, markdown_path)
        raise
    return TerminalReviewPacketResult(
        packet_id=packet_id,
        packet_fingerprint=semantic_fingerprint,
        event_id=request.event_id,
        event_kind=event["kind"],
        json_path=json_path,
        markdown_path=markdown_path,
        duplicate=duplicate,
    )


def _read_documents(request: TerminalReviewPacketRequest) -> list[_InputDocument]:
    paths = {
        "shadow_state": request.state_path,
        "decision_cycles": request.decision_cycles_path,
        "handoff": request.handoff_path,
        "source_report": request.report_path,
        "sample_activation": request.activation_path,
        "selection_policy": request.selection_policy_path,
    }
    resolved = [Path(path).resolve() for path in paths.values()]
    if len(set(resolved)) != len(resolved):
        raise TerminalReviewPacketError("Every input role must use a distinct file.")
    documents = []
    for role, path_value in paths.items():
        path = Path(path_value).resolve()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise TerminalReviewPacketError(
                f"Required {role.replace('_', ' ')} input cannot be read: {type(exc).__name__}."
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TerminalReviewPacketError(
                f"Required {role.replace('_', ' ')} input is not valid UTF-8 JSON."
            ) from exc
        documents.append(
            _InputDocument(role, path, raw, hashlib.sha256(raw).hexdigest(), payload)
        )
    return documents


def _load_state(payload: Any):
    try:
        return shadow_state_from_dict(_require_object(payload, "Shadow state"))
    except (TypeError, ValueError, RuntimeError) as exc:
        raise TerminalReviewPacketError(
            f"Shadow state is invalid: {_redact_error(str(exc))}"
        ) from exc


def _load_cycles(payload: Any) -> tuple[dict[str, Any], ...]:
    root = _require_object(payload, "decision-cycle state")
    cycles = root.get("cycles")
    if root.get("schema_version") != 1 or not isinstance(cycles, list):
        raise TerminalReviewPacketError("Decision-cycle state has an unsupported schema.")
    if any(not isinstance(item, dict) for item in cycles):
        raise TerminalReviewPacketError("Decision-cycle state contains a malformed cycle.")
    cycle_ids = [str(item.get("cycle_id", "")) for item in cycles]
    if any(not value for value in cycle_ids) or len(cycle_ids) != len(set(cycle_ids)):
        raise TerminalReviewPacketError("Decision-cycle identities are missing or duplicated.")
    return tuple(dict(item) for item in cycles)


def _load_activation(payload: Any) -> dict[str, Any]:
    activation = _require_object(payload, "sample activation")
    metadata = _require_object(activation.get("sample_metadata"), "sample metadata")
    expected_activation_fields = {"schema_version", "activated_at", "sample_metadata"}
    expected_metadata_fields = {
        "sample_version",
        "strategy_configuration_fingerprint",
        "strategy_configuration_json",
        "fill_model_version",
        "evidence_schema_version",
        "official_sample_authorized",
    }
    if set(activation) != expected_activation_fields or set(metadata) != expected_metadata_fields:
        raise TerminalReviewPacketError(
            "Sample activation contains missing or unsupported fields."
        )
    if _parse_datetime(activation.get("activated_at")) is None:
        raise TerminalReviewPacketError("Sample activation timestamp is invalid or unzoned.")
    try:
        sample = ShadowSampleMetadata(**metadata)
    except (TypeError, ValueError) as exc:
        raise TerminalReviewPacketError("Sample activation metadata is malformed.") from exc
    findings = shadow_sample_metadata_findings(sample, require_current_contract=True)
    if not sample.official_sample_authorized:
        findings.append("Official sample authorization is false.")
    if activation.get("schema_version") != 1 or findings:
        raise TerminalReviewPacketError(
            "Sample activation is invalid: " + _redact_error(" | ".join(findings))
        )
    return activation


def _load_selection_policy(payload: Any) -> dict[str, Any]:
    policy = _require_object(payload, "selection policy")
    try:
        loaded = ShadowSelectionPolicy(**policy)
        validate_shadow_selection_policy(loaded)
    except (ShadowStateError, TypeError, ValueError) as exc:
        raise TerminalReviewPacketError(
            "Selection policy is invalid: " + _redact_error(str(exc))
        ) from exc
    if policy != asdict(loaded):
        raise TerminalReviewPacketError(
            "Selection policy contains unsupported or coerced fields."
        )
    return policy


def _resolve_event(
    event_id: str,
    trades: Sequence[ShadowTrade],
    cycles: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    matching_trades = [trade for trade in trades if trade.shadow_trade_id == event_id]
    matching_cycles = [cycle for cycle in cycles if cycle.get("cycle_id") == event_id]
    if len(matching_trades) + len(matching_cycles) != 1:
        raise TerminalReviewPacketError(
            "Event ID must identify exactly one Shadow trade or decision cycle."
        )
    if matching_trades:
        trade = matching_trades[0]
        if trade.status not in TERMINAL_TRADE_STATES:
            raise TerminalReviewPacketError(
                f"Shadow trade is nonterminal ({trade.status or 'UNKNOWN'})."
            )
        audit = audit_shadow_trade(trade)
        if not audit.passed:
            reasons = " | ".join(finding.message for finding in audit.findings)
            raise TerminalReviewPacketError(
                "Shadow trade audit failed: " + _redact_error(reasons)
            )
        matching_trade_cycles = [
            cycle for cycle in cycles if cycle.get("cycle_id") == trade.decision_cycle_id
        ]
        if len(matching_trade_cycles) != 1:
            raise TerminalReviewPacketError(
                "Terminal trade lacks exactly one matching decision cycle."
            )
        return {"kind": _trade_event_kind(trade), "trade": trade, "cycle": matching_trade_cycles[0]}

    cycle = matching_cycles[0]
    if cycle.get("cycle_kind") != "DECISION":
        raise TerminalReviewPacketError("Requested cycle is not a decision event.")
    if cycle.get("status") not in NO_TRADE_TERMINAL_STATUSES:
        raise TerminalReviewPacketError(
            f"Decision cycle is not an accepted terminal no-trade event ({cycle.get('status')})."
        )
    return {"kind": "NO_TRADE", "trade": None, "cycle": cycle}


def _validate_report_identity(
    report: _InputDocument,
    trade: ShadowTrade | None,
    cycle: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> None:
    expected = {
        str(cycle.get("report_sha256", "")),
        str(handoff.get("reportSha256", "")),
    }
    if trade is not None:
        expected.add(trade.evidence.source_sha256)
    if "" in expected or expected != {report.sha256}:
        raise TerminalReviewPacketError(
            "Source report hash contradicts the event, handoff, or frozen trade evidence."
        )


def _validate_event_chain(
    trade: ShadowTrade | None,
    cycle: Mapping[str, Any],
    handoff: Mapping[str, Any],
    activation: Mapping[str, Any],
    selection_policy: Mapping[str, Any],
    all_trades: Sequence[ShadowTrade],
) -> None:
    findings = shadow_handoff_findings(
        handoff,
        expected_report_sha256=str(cycle.get("report_sha256", "")),
    )
    if findings:
        raise TerminalReviewPacketError(
            "Handoff validation failed: " + _redact_error(" | ".join(findings))
        )
    if handoff.get("decisionCycleId") != cycle.get("cycle_id"):
        raise TerminalReviewPacketError("Handoff and decision-cycle identities conflict.")
    metadata = _require_object(activation.get("sample_metadata"), "sample metadata")
    for key in ("sample_version", "strategy_configuration_fingerprint"):
        if selection_policy.get(key) != metadata.get(key):
            raise TerminalReviewPacketError(
                f"Selection policy and sample activation disagree on {key}."
            )

    if trade is None:
        if cycle.get("shadow_trade_id") not in {None, ""}:
            raise TerminalReviewPacketError("No-trade cycle unexpectedly identifies a trade.")
        if handoff.get("status") != "CYCLE_COMPLETED_NO_TRADE" or handoff.get(
            "shadowTradeId"
        ) not in {None, ""}:
            raise TerminalReviewPacketError("No-trade handoff contains trade state.")
        if any(item.decision_cycle_id == cycle.get("cycle_id") for item in all_trades):
            raise TerminalReviewPacketError("No-trade cycle has a persisted Shadow trade.")
        cycle_sample = cycle.get("sample_version")
        cycle_fill_model = cycle.get("fill_model_version")
        if cycle_sample not in {None, "", metadata.get("sample_version")}:
            raise TerminalReviewPacketError("Decision cycle sample version is contradictory.")
        if cycle_fill_model not in {None, "", metadata.get("fill_model_version")}:
            raise TerminalReviewPacketError("Decision cycle fill-model version is contradictory.")
        if cycle.get("selection_policy_fingerprint") != selection_policy.get(
            "selection_policy_fingerprint"
        ):
            raise TerminalReviewPacketError(
                "No-trade cycle selection-policy identity is contradictory."
            )
        return

    if not trade.sample_metadata.official_sample_authorized:
        raise TerminalReviewPacketError("Terminal trade is not part of an authorized sample.")
    comparisons = {
        "sample version": (
            trade.sample_metadata.sample_version,
            metadata.get("sample_version"),
        ),
        "strategy configuration": (
            trade.sample_metadata.strategy_configuration_fingerprint,
            metadata.get("strategy_configuration_fingerprint"),
        ),
        "fill model": (
            trade.sample_metadata.fill_model_version,
            metadata.get("fill_model_version"),
        ),
        "evidence schema": (
            trade.sample_metadata.evidence_schema_version,
            metadata.get("evidence_schema_version"),
        ),
        "selection policy": (
            trade.selection_policy_fingerprint,
            selection_policy.get("selection_policy_fingerprint"),
        ),
    }
    mismatches = [name for name, values in comparisons.items() if values[0] != values[1]]
    if mismatches:
        raise TerminalReviewPacketError(
            "Event chain version mismatch: " + ", ".join(mismatches) + "."
        )
    if cycle.get("shadow_trade_id") != trade.shadow_trade_id:
        raise TerminalReviewPacketError("Decision cycle does not identify the requested trade.")
    if cycle.get("status") != "TRADE_STARTED":
        raise TerminalReviewPacketError("Trade decision cycle is not terminal TRADE_STARTED evidence.")
    if handoff.get("status") != "CYCLE_COMPLETED_TRADE_CREATED":
        raise TerminalReviewPacketError("Trade event has a no-trade or incomplete handoff.")
    if handoff.get("shadowTradeId") != trade.shadow_trade_id:
        raise TerminalReviewPacketError("Handoff identifies a different Shadow trade.")
    trade_cycle_comparisons = {
        "selected symbol": (trade.symbol, cycle.get("selected_symbol")),
        "selected rank": (trade.candidate_rank, cycle.get("selected_rank")),
        "opportunity": (trade.opportunity_id, cycle.get("opportunity_id")),
        "setup": (trade.setup_id, cycle.get("setup_id")),
        "TradePlan": (trade.trade_plan_id, cycle.get("trade_plan_id")),
        "Shadow selection": (
            trade.shadow_selection_id,
            cycle.get("shadow_selection_id"),
        ),
        "selector arm": (trade.selector_arm_id, cycle.get("selector_arm_id")),
        "constitution": (trade.constitution_hash, cycle.get("constitution_hash")),
        "selection policy": (
            trade.selection_policy_fingerprint,
            cycle.get("selection_policy_fingerprint"),
        ),
    }
    contradictions = [
        name for name, values in trade_cycle_comparisons.items() if values[0] != values[1]
    ]
    if contradictions:
        raise TerminalReviewPacketError(
            "Trade and decision cycle disagree on " + ", ".join(contradictions) + "."
        )


def _trade_sections(trade: ShadowTrade, cycle: Mapping[str, Any]) -> dict[str, Any]:
    candidate = trade.evidence.candidate_payload()
    try:
        plan = json.loads(trade.trade_plan_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TerminalReviewPacketError("Frozen TradePlan JSON is invalid.") from exc
    if not isinstance(plan, dict):
        raise TerminalReviewPacketError("Frozen TradePlan JSON must contain an object.")
    risk = trade.risk_result_payload()
    order = trade.order
    position = trade.position
    outcome = trade.outcome
    assessment = _find_assessment(cycle, trade.symbol)
    order_timeline = [_ledger_row(event.to_dict()) for event in trade.ledger_events]
    direction = shadow_trade_direction(trade)
    session_date = trade.decision_timestamp[:10] if trade.decision_timestamp else None
    setup = trade.setup_type or _nested(candidate, "scoring", "catalyst_cluster")
    catalyst = trade.catalyst or _nested(candidate, "scoring", "catalyst_summary")
    plan_source = f"ShadowTrade:{trade.shadow_trade_id}.trade_plan_json"
    risk_source = f"ShadowTrade:{trade.shadow_trade_id}.risk_result_json"
    outcome_source = f"ShadowTrade:{trade.shadow_trade_id}.outcome"

    sections = {
        "A_EVENT_IDENTITY": {
            "sampleVersion": _fact_or_missing(trade.sample_metadata.sample_version, "ShadowTrade.sample_metadata.sample_version"),
            "strategyConfigurationFingerprint": _fact_or_missing(trade.sample_metadata.strategy_configuration_fingerprint, "ShadowTrade.sample_metadata.strategy_configuration_fingerprint"),
            "fillModelVersion": _fact_or_missing(trade.sample_metadata.fill_model_version, "ShadowTrade.sample_metadata.fill_model_version"),
            "evidenceSchemaVersion": stored(trade.sample_metadata.evidence_schema_version, "ShadowTrade.sample_metadata.evidence_schema_version"),
            "sessionDate": derived(session_date, inputs=["ShadowTrade.decision_timestamp"], formula="calendar date prefix of the offset-aware decision timestamp"),
            "symbol": stored(trade.symbol, "ShadowTrade.symbol"),
            "direction": (
                stored(direction, "ShadowPosition.direction")
                if position is not None
                else derived(
                    direction,
                    inputs=["ShadowOrder.side"],
                    formula="buy maps to LONG and sell/short maps to SHORT",
                )
            ),
            "setupFamily": _fact_or_missing(setup, "ShadowTrade.setup_type or frozen candidate catalyst_cluster"),
            "catalystIdentity": _fact_or_missing(catalyst, "ShadowTrade.catalyst or frozen candidate catalyst_summary"),
            "terminalLifecycle": stored(_trade_event_kind(trade), "ShadowTrade.status and ShadowOutcome.classification"),
        },
        "B_CAPTURE_AND_CANDIDATE_EVIDENCE": {
            "captureSource": _fact_or_missing(trade.evidence.source_capture_path, "ShadowEvidenceSnapshot.source_capture_path"),
            "captureTimestamp": _fact_or_missing(trade.evidence.source_capture_time, "ShadowEvidenceSnapshot.source_capture_time"),
            "reportGeneratedAt": _fact_or_missing(trade.evidence.source_generated_at, "ShadowEvidenceSnapshot.source_generated_at"),
            "sourceReportSha256": stored(trade.evidence.source_sha256, "ShadowEvidenceSnapshot.source_sha256"),
            "candidateId": stored(trade.candidate_id, "ShadowTrade.candidate_id"),
            "candidateRank": stored(trade.candidate_rank, "ShadowTrade.candidate_rank"),
            "candidateScore": stored(trade.candidate_score, "ShadowTrade.candidate_score"),
            "fatalWarnings": stored(list(assessment.get("fatal_warnings", [])), "DecisionCycle.candidate_assessments.fatal_warnings"),
            "informationalWarnings": stored(list(assessment.get("informational_warnings", [])), "DecisionCycle.candidate_assessments.informational_warnings"),
            "dataQuality": _fact_or_missing(trade.data_quality_state, "ShadowTrade.data_quality_state"),
            "persistedIndicators": stored(_candidate_indicators(candidate), "ShadowEvidenceSnapshot.candidate_json (allowlisted fields)"),
        },
        "C_TRADE_PLAN": {
            "tradePlanId": stored(trade.trade_plan_id, "ShadowTrade.trade_plan_id"),
            "planFingerprint": stored(trade.plan_fingerprint, "ShadowTrade.plan_fingerprint"),
            "entry": _fact_or_missing(plan.get("bullish_entry"), plan_source),
            "stop": _fact_or_missing(plan.get("bullish_stop"), plan_source),
            "targets": stored([value for value in (plan.get("bullish_target_1"), plan.get("bullish_target_2")) if value is not None], plan_source),
            "initialRisk": _fact_or_missing(plan.get("estimated_dollar_risk"), plan_source),
            "rewardRisk": _fact_or_missing(plan.get("risk_reward_ratio"), plan_source),
            "invalidationRules": stored(list(plan.get("blocking_reasons", [])), plan_source),
            "warnings": stored(list(plan.get("warnings", [])), plan_source),
        },
        "D_RISK_GOVERNOR": {
            "riskDecisionId": stored(trade.risk_decision_id, "ShadowTrade.risk_decision_id"),
            "result": _fact_or_missing(risk.get("status"), risk_source),
            "allowedForSimulation": stored(bool(risk.get("allows_simulation")), risk_source),
            "gateResults": stored(_risk_gate_results(risk, trade.ledger_events), risk_source + " and ledger risk event"),
            "blockingReasons": stored(list(trade.risk_rejection_reasons or tuple(risk.get("reasons", []))), "ShadowTrade.risk_rejection_reasons"),
        },
        "E_SELECTION_RESULT": {
            "decisionCycleId": stored(trade.decision_cycle_id, "ShadowTrade.decision_cycle_id"),
            "status": stored(str(cycle.get("status", "")), "DecisionCycle.status"),
            "reason": _fact_or_missing(cycle.get("reason"), "DecisionCycle.reason"),
            "selectedSymbol": stored(cycle.get("selected_symbol"), "DecisionCycle.selected_symbol"),
            "selectedRank": stored(cycle.get("selected_rank"), "DecisionCycle.selected_rank"),
            "opportunityId": stored(trade.opportunity_id, "ShadowTrade.opportunity_id"),
            "setupId": stored(trade.setup_id, "ShadowTrade.setup_id"),
            "tradePlanId": stored(trade.trade_plan_id, "ShadowTrade.trade_plan_id"),
            "positionId": _fact_or_missing(
                position.position_id if position else None,
                "ShadowPosition.position_id",
            ),
            "openedAt": _fact_or_missing(
                position.opened_at if position else None,
                "ShadowPosition.opened_at",
            ),
            "linkageStatus": stored(
                shadow_identity_linkage_status(trade),
                "Persisted exact lifecycle-position provenance",
            ),
            "selectorArmId": stored(trade.selector_arm_id, "ShadowTrade.selector_arm_id"),
            "selectionPolicyFingerprint": stored(
                trade.selection_policy_fingerprint,
                "ShadowTrade.selection_policy_fingerprint",
            ),
            "rejectionReasons": stored(list(assessment.get("rejection_reasons", [])), "DecisionCycle.candidate_assessments.rejection_reasons"),
        },
        "F_EXECUTION_AND_LIFECYCLE": {
            "simulationCommandId": stored(
                trade.simulation_command_id, "ShadowTrade.simulation_command_id"
            ),
            "order": stored(_order_row(order), "ShadowTrade.order") if order else missing("No order evidence was persisted."),
            "position": stored(_position_row(position), "ShadowTrade.position") if position else missing("No position evidence was persisted."),
            "chronology": stored(order_timeline, "ShadowTrade.ledger_events (allowlisted fields)"),
            "activeMark": stored(_mark_row(trade.executable_mark), "ShadowTrade.executable_mark") if trade.executable_mark else missing("No executable mark was persisted."),
            "exit": stored(_outcome_row(outcome), outcome_source) if outcome else missing("This terminal state has no completed outcome."),
            "lastReason": _fact_or_missing(trade.last_reason, "ShadowTrade.last_reason"),
        },
        "G_PERFORMANCE": {
            "executableDollarPnl": _fact_or_missing(outcome.executable_pnl if outcome else None, outcome_source),
            "executableR": _fact_or_missing(outcome.r_multiple if outcome else None, outcome_source),
            "grossDollarPnl": _fact_or_missing(outcome.gross_pnl if outcome else None, outcome_source),
            "idealResult": missing("No separately persisted ideal result exists in this event chain."),
            "mfeDollars": _fact_or_missing(outcome.mfe_dollars if outcome else None, outcome_source),
            "maeDollars": _fact_or_missing(outcome.mae_dollars if outcome else None, outcome_source),
            "holdingDurationSeconds": _fact_or_missing(outcome.duration_seconds if outcome else None, outcome_source),
            "entryToExitLatencySeconds": _duration_derivation(position.opened_at if position else None, outcome.exit_timestamp if outcome else None, "ShadowPosition.opened_at", "ShadowOutcome.exit_timestamp"),
            "grossExecutableGap": _difference_derivation(outcome.gross_pnl if outcome else None, outcome.executable_pnl if outcome else None),
        },
        "H_COUNTERFACTUALS_AND_BENCHMARKS": _counterfactual_section(cycle, trade.symbol),
        "I_DATA_AND_SYSTEM_QUALITY": _quality_section(cycle, assessment),
        "J_REVIEW_QUESTIONS": _questions_section(),
    }
    return sections


def _no_trade_sections(cycle: Mapping[str, Any]) -> dict[str, Any]:
    assessments = [
        _assessment_row(item)
        for item in cycle.get("candidate_assessments", [])
        if isinstance(item, dict)
    ]
    sections = {
        "A_EVENT_IDENTITY": {
            "sampleVersion": _fact_or_missing(cycle.get("sample_version"), "DecisionCycle.sample_version"),
            "strategyConfigurationFingerprint": _fact_or_missing(cycle.get("strategy_configuration_fingerprint"), "DecisionCycle.strategy_configuration_fingerprint"),
            "fillModelVersion": _fact_or_missing(cycle.get("fill_model_version"), "DecisionCycle.fill_model_version"),
            "evidenceSchemaVersion": stored(cycle.get("schema_version"), "DecisionCycle.schema_version"),
            "sessionDate": derived(str(cycle.get("decision_at", ""))[:10] or None, inputs=["DecisionCycle.decision_at"], formula="calendar date prefix of the offset-aware decision timestamp"),
            "symbol": missing("A terminal no-trade cycle does not identify an official traded symbol."),
            "direction": missing("No trade direction exists for a no-trade cycle."),
            "setupFamily": missing("No setup was selected."),
            "catalystIdentity": missing("No catalyst was selected."),
            "terminalLifecycle": stored("NO_TRADE", "DecisionCycle.status"),
        },
        "B_CAPTURE_AND_CANDIDATE_EVIDENCE": {
            "captureSource": _fact_or_missing(cycle.get("source_capture_path"), "DecisionCycle.source_capture_path"),
            "captureTimestamp": _fact_or_missing(cycle.get("source_capture_time"), "DecisionCycle.source_capture_time"),
            "reportGeneratedAt": _fact_or_missing(cycle.get("report_generated_at"), "DecisionCycle.report_generated_at"),
            "sourceReportSha256": stored(cycle.get("report_sha256"), "DecisionCycle.report_sha256"),
            "candidateAssessments": stored(assessments, "DecisionCycle.candidate_assessments (allowlisted fields)"),
            "eligibleCandidateCount": stored(cycle.get("eligible_candidate_count", 0), "DecisionCycle.eligible_candidate_count"),
            "dataQuality": _fact_or_missing(cycle.get("data_quality_state"), "DecisionCycle.data_quality_state"),
        },
        "C_TRADE_PLAN": {"status": missing("No TradePlan was selected for this terminal cycle.")},
        "D_RISK_GOVERNOR": {
            "candidateRiskResults": stored(
                [{"symbol": item.get("symbol"), "risk": item.get("risk"), "rejectionReasons": item.get("rejectionReasons")} for item in assessments],
                "DecisionCycle.candidate_assessments",
            )
        },
        "E_SELECTION_RESULT": {
            "decisionCycleId": stored(cycle.get("cycle_id"), "DecisionCycle.cycle_id"),
            "status": stored(cycle.get("status"), "DecisionCycle.status"),
            "reason": _fact_or_missing(cycle.get("reason"), "DecisionCycle.reason"),
            "selectedSymbol": stored(None, "DecisionCycle.selected_symbol"),
            "selectedRank": stored(None, "DecisionCycle.selected_rank"),
            "proofNoOrderOrPosition": derived(True, inputs=["DecisionCycle.shadow_trade_id", "ShadowTradingState.trades"], formula="cycle has no trade identity and no persisted trade references the cycle"),
        },
        "F_EXECUTION_AND_LIFECYCLE": {
            "terminalNoTradeReason": _fact_or_missing(cycle.get("reason"), "DecisionCycle.reason"),
            "order": missing("No order was created."),
            "position": missing("No position was created."),
            "outcome": missing("No trade outcome exists for a no-trade cycle."),
        },
        "G_PERFORMANCE": {"status": missing("Performance values do not exist for a no-trade cycle.")},
        "H_COUNTERFACTUALS_AND_BENCHMARKS": _counterfactual_section(cycle, None),
        "I_DATA_AND_SYSTEM_QUALITY": _quality_section(cycle, {}),
        "J_REVIEW_QUESTIONS": _questions_section(),
    }
    return sections


def _counterfactual_section(cycle: Mapping[str, Any], selected_symbol: str | None) -> dict[str, Any]:
    assessments = [item for item in cycle.get("candidate_assessments", []) if isinstance(item, dict)]
    eligible_unselected = [
        {"symbol": item.get("symbol"), "rank": item.get("canonical_rank"), "status": "COUNTERFACTUAL — NOT AN OFFICIAL TRADE"}
        for item in assessments
        if item.get("eligible") is True and item.get("symbol") != selected_symbol
    ]
    marks = [
        _allowlist(item, ("symbol", "available", "measurement", "latest_timestamp", "return_percent", "reason"))
        for item in cycle.get("counterfactual_marks", [])
        if isinstance(item, dict)
    ]
    for item in marks:
        item["status"] = "COUNTERFACTUAL — NOT AN OFFICIAL TRADE"
    return {
        "disclaimer": stored("COUNTERFACTUAL — NOT AN OFFICIAL TRADE", "Packet policy"),
        "eligibleUnselected": stored(eligible_unselected, "DecisionCycle.candidate_assessments"),
        "deterministicRandomCandidate": _fact_or_missing(
            (
                {
                    **cycle["deterministic_random_eligible"],
                    "status": "COUNTERFACTUAL — NOT AN OFFICIAL TRADE",
                }
                if isinstance(cycle.get("deterministic_random_eligible"), dict)
                else cycle.get("deterministic_random_eligible")
            ),
            "DecisionCycle.deterministic_random_eligible",
        ),
        "benchmarks": stored(_benchmark_rows(cycle.get("benchmark_baselines")), "DecisionCycle.benchmark_baselines"),
        "observedMarks": stored(marks, "DecisionCycle.counterfactual_marks"),
    }


def _quality_section(cycle: Mapping[str, Any], assessment: Mapping[str, Any]) -> dict[str, Any]:
    decision_at = cycle.get("decision_at")
    capture_at = cycle.get("source_capture_time")
    report_at = cycle.get("report_generated_at")
    return {
        "captureAgeSeconds": _duration_derivation(capture_at, decision_at, "DecisionCycle.source_capture_time", "DecisionCycle.decision_at"),
        "reportAgeSeconds": _duration_derivation(report_at, decision_at, "DecisionCycle.report_generated_at", "DecisionCycle.decision_at"),
        "selectionLatencySeconds": _duration_derivation(report_at, decision_at, "DecisionCycle.report_generated_at", "DecisionCycle.decision_at"),
        "quoteAgeSeconds": _fact_or_missing(assessment.get("quote_age_seconds"), "DecisionCycle.candidate_assessments.quote_age_seconds"),
        "providerIdentity": _fact_or_missing(cycle.get("source_provider"), "DecisionCycle.source_provider"),
        "clockEvidence": _fact_or_missing(cycle.get("clock_evidence"), "DecisionCycle.clock_evidence"),
        "preArmClockEvidence": _fact_or_missing(cycle.get("pre_arm_clock_skew_proof"), "DecisionCycle.pre_arm_clock_skew_proof"),
        "decisionClockEvidence": _fact_or_missing(cycle.get("decision_clock_skew_proof"), "DecisionCycle.decision_clock_skew_proof"),
        "missingExpectedCycles": _fact_or_missing(cycle.get("missing_expected_cycles"), "DecisionCycle.missing_expected_cycles"),
        "serviceOrEngineHostAnomalies": _fact_or_missing(cycle.get("system_anomalies"), "DecisionCycle.system_anomalies"),
        "restartOrDowntimeEvidence": _fact_or_missing(cycle.get("downtime_evidence"), "DecisionCycle.downtime_evidence"),
    }


def _questions_section() -> dict[str, Any]:
    questions = (
        "Which persisted signals supported selection?",
        "Which persisted evidence opposed selection?",
        "Was the executable fill materially worse than the plan?",
        "Was maximum adverse excursion consistent with the stored stop design?",
        "Did the move occur before the system could act?",
        "Did the selected candidate outperform the preserved alternatives?",
        "Were any data-quality or availability failures present?",
    )
    return {f"question{index}": review_question(text) for index, text in enumerate(questions, 1)}


def _trade_event_kind(trade: ShadowTrade) -> str:
    if trade.status == "completed" and trade.outcome is not None:
        classification = trade.outcome.classification.upper()
        if classification in {"WIN", "WINNER"}:
            return "COMPLETED_WINNER"
        if classification in {"LOSS", "LOSER"}:
            return "COMPLETED_LOSER"
        return "COMPLETED_FLAT"
    return {
        "entry_rejected": "UNFILLED_ORDER",
        "cancelled": "CANCELLED_ORDER",
        "blocked": "RISK_BLOCKED",
        "ambiguous_exit": "INVALIDATED_TRADE",
    }[trade.status]


def _terminal_timestamp(
    trade: ShadowTrade | None,
    cycle: Mapping[str, Any],
    handoff: Mapping[str, Any],
) -> str:
    candidates: list[Any] = []
    if trade is not None:
        if trade.outcome is not None:
            candidates.append(trade.outcome.exit_timestamp)
        if trade.order is not None:
            candidates.append(trade.order.last_update_at)
        candidates.extend((trade.last_observation_timestamp, trade.decision_timestamp))
    candidates.extend((handoff.get("recordedAt"), handoff.get("completionTimestamp"), cycle.get("updated_at"), cycle.get("decision_at")))
    for value in candidates:
        if _parse_datetime(value) is not None:
            return str(value)
    raise TerminalReviewPacketError("Terminal event lacks an offset-aware terminal timestamp.")


def _find_assessment(cycle: Mapping[str, Any], symbol: str) -> dict[str, Any]:
    matches = [
        item
        for item in cycle.get("candidate_assessments", [])
        if isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol.upper()
    ]
    if len(matches) != 1:
        raise TerminalReviewPacketError("Decision cycle lacks exactly one assessment for the trade symbol.")
    return matches[0]


def _assessment_row(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": item.get("symbol"),
        "canonicalRank": item.get("canonical_rank"),
        "compositeScore": item.get("composite_score"),
        "eligible": item.get("eligible"),
        "rejectionReasons": list(item.get("rejection_reasons", [])),
        "fatalWarnings": list(item.get("fatal_warnings", [])),
        "informationalWarnings": list(item.get("informational_warnings", [])),
        "risk": _allowlist(item.get("risk"), ("status", "allows_simulation", "reasons")),
        "quoteAgeSeconds": item.get("quote_age_seconds"),
        "opportunityId": item.get("opportunity_id"),
        "planFingerprint": item.get("plan_fingerprint"),
    }


def _candidate_indicators(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "marketData": _allowlist(
            candidate.get("market_data"),
            ("last_price", "spread_percent", "relative_volume", "intraday_volume", "average_daily_volume_20"),
        ),
        "scoring": _allowlist(
            candidate.get("scoring"),
            ("momentum_score", "news_score", "composite_score", "catalyst_cluster", "catalyst_confidence"),
        ),
        "opportunityNotes": list(candidate.get("opportunity_notes", [])) if isinstance(candidate.get("opportunity_notes"), list) else [],
    }


def _risk_gate_results(risk: Mapping[str, Any], ledger_events: Iterable[Any]) -> dict[str, Any]:
    event = next((item for item in ledger_events if item.requested_action == "risk_gate_evaluated"), None)
    payload = event.payload if event is not None else {}
    return {
        "status": risk.get("status"),
        "allowsSimulation": risk.get("allows_simulation"),
        "buyingPower": payload.get("buying_power_result"),
        "positionConcurrency": payload.get("position_concurrency_result"),
        "dailyLoss": payload.get("daily_loss_result"),
        "session": payload.get("session_result"),
    }


def _ledger_row(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "eventId": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "eventType": event.get("event_type"),
        "requestedAction": event.get("requested_action"),
        "result": event.get("result"),
        "reason": event.get("reason"),
        "payload": _allowlist(
            event.get("payload"),
            (
                "previous_state",
                "new_state",
                "quote_provider",
                "provider_timestamp",
                "receipt_timestamp",
                "executable_mark",
                "filled_quantity",
                "remaining_quantity",
                "fill_price",
                "exit_reason",
                "order_id",
                "position_id",
                "outcome_id",
            ),
        ),
    }


def _order_row(order: Any) -> dict[str, Any]:
    return {
        "orderId": order.order_id,
        "side": order.side,
        "quantity": order.quantity,
        "filledQuantity": order.filled_quantity,
        "remainingQuantity": order.remaining_quantity,
        "orderType": order.order_type,
        "limitPrice": order.limit_price,
        "status": order.status,
        "submittedAt": order.submitted_at,
        "averageFillPrice": order.average_fill_price,
        "lastUpdateAt": order.last_update_at,
        "reason": order.reason,
    }


def _position_row(position: Any) -> dict[str, Any]:
    return {
        "positionId": position.position_id,
        "opportunityId": position.opportunity_id or None,
        "setupId": position.setup_id or None,
        "tradePlanId": position.trade_plan_id or None,
        "direction": position.direction,
        "quantity": position.quantity,
        "averageEntryPrice": position.average_entry_price,
        "openedAt": position.opened_at,
        "stopPrice": position.stop_price,
        "targetPrice": position.target_price,
        "highestPrice": position.highest_price,
        "lowestPrice": position.lowest_price,
    }


def _outcome_row(outcome: Any) -> dict[str, Any]:
    return {
        "outcomeId": outcome.outcome_id,
        "status": outcome.status,
        "classification": outcome.classification,
        "exitTimestamp": outcome.exit_timestamp,
        "exitReason": outcome.exit_reason,
        "exitPrice": outcome.exit_price,
    }


def _mark_row(mark: Any) -> dict[str, Any]:
    return {
        "condition": mark.condition,
        "quoteIdentity": mark.quote_identity,
        "provider": mark.provider,
        "providerTimestamp": mark.provider_timestamp,
        "receiptTimestamp": mark.receipt_timestamp,
        "bid": mark.bid,
        "ask": mark.ask,
        "executableMark": mark.executable_mark,
        "unrealizedPnl": mark.unrealized_pnl,
        "unrealizedR": mark.unrealized_r,
        "mfeDollars": mark.mfe_dollars,
        "maeDollars": mark.mae_dollars,
        "reason": mark.reason,
    }


def _benchmark_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [
        {
            "symbol": str(symbol),
            "baseline": _allowlist(payload, ("timestamp", "source", "bid", "ask", "last")),
            "status": "COUNTERFACTUAL — NOT AN OFFICIAL TRADE",
        }
        for symbol, payload in sorted(value.items())
    ]


def _duration_derivation(start: Any, end: Any, start_name: str, end_name: str) -> dict[str, Any]:
    start_at = _parse_datetime(start)
    end_at = _parse_datetime(end)
    if start_at is None or end_at is None:
        return missing(f"Cannot derive duration without valid {start_name} and {end_name}.")
    return derived(
        round((end_at - start_at).total_seconds(), 3),
        inputs=[start_name, end_name],
        formula=f"{end_name} - {start_name}, expressed in seconds",
        rounding="nearest 0.001 second",
    )


def _difference_derivation(gross: Any, executable: Any) -> dict[str, Any]:
    if not isinstance(gross, (int, float)) or not isinstance(executable, (int, float)):
        return missing("Gross and executable P&L are both required for the gap derivation.")
    return derived(
        round(float(gross) - float(executable), 4),
        inputs=["ShadowOutcome.gross_pnl", "ShadowOutcome.executable_pnl"],
        formula="gross_pnl - executable_pnl",
        rounding="nearest 0.0001 dollar",
    )


def _fact_or_missing(value: Any, source: str) -> dict[str, Any]:
    return (
        stored(value, source)
        if value is not None and value != ""
        else missing(f"{source} was not persisted.")
    )


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _allowlist(value: Any, keys: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value.get(key) for key in keys if key in value}


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TerminalReviewPacketError(f"{label} must contain a JSON object.")
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _derived_definitions() -> dict[str, Any]:
    return {
        "sessionDate": {
            "inputs": ["decision timestamp"],
            "formula": "calendar date prefix of the offset-aware timestamp",
            "rounding": "none",
            "missingBehavior": "MISSING",
        },
        "durations": {
            "inputs": ["named offset-aware start timestamp", "named offset-aware end timestamp"],
            "formula": "end - start in seconds",
            "rounding": "nearest 0.001 second",
            "missingBehavior": "MISSING",
        },
        "grossExecutableGap": {
            "inputs": ["gross_pnl", "executable_pnl"],
            "formula": "gross_pnl - executable_pnl",
            "rounding": "nearest 0.0001 dollar",
            "missingBehavior": "MISSING",
        },
        "packetFingerprint": {
            "inputs": ["source identity", "terminal timestamp", "input hashes", "review sections"],
            "formula": "SHA-256 of canonical sorted compact JSON before envelope decoration",
            "rounding": "not applicable",
            "missingBehavior": "fail closed",
        },
    }


def _validate_packet_shape(packet: Mapping[str, Any]) -> None:
    if packet.get("schemaVersion") != PACKET_SCHEMA_VERSION:
        raise TerminalReviewPacketError("Packet schema is unsupported.")
    fingerprint = str(packet.get("packetFingerprint", ""))
    if not _SHA256.fullmatch(fingerprint):
        raise TerminalReviewPacketError("Packet fingerprint is invalid.")
    sections = packet.get("sections")
    if not isinstance(sections, dict) or len(sections) != 10:
        raise TerminalReviewPacketError("Packet does not contain all ten review sections.")
    for section_name, fields in sections.items():
        if not isinstance(fields, dict) or not fields:
            raise TerminalReviewPacketError(f"Packet section {section_name} is empty.")
        for field_name, field in fields.items():
            if not isinstance(field, dict) or field.get("classification") not in FIELD_CLASSIFICATIONS:
                raise TerminalReviewPacketError(
                    f"Packet field {section_name}.{field_name} lacks a valid classification."
                )


def verify_packet_security(
    packet_bytes: bytes,
    *,
    known_sensitive_values: Sequence[str] = (),
) -> None:
    text = packet_bytes.decode("utf-8")
    findings = []
    if _SENSITIVE_KEY.search(text):
        findings.append("sensitive key name")
    if _SENSITIVE_VALUE.search(text):
        findings.append("credential-like value")
    for value in known_sensitive_values:
        if value and value in text:
            findings.append("known sensitive value")
    if findings:
        raise TerminalReviewPacketError(
            "Packet security scan failed: " + ", ".join(sorted(set(findings))) + "."
        )


def render_terminal_review_markdown(packet: Mapping[str, Any]) -> str:
    identity = packet["sourceEventIdentity"]
    lines = [
        "# Momentum Hunter Terminal Shadow Review Packet",
        "",
        f"- Packet ID: `{packet['packetId']}`",
        f"- Packet fingerprint: `{packet['packetFingerprint']}`",
        f"- Schema version: {packet['schemaVersion']}",
        f"- Event ID: `{identity['eventId']}`",
        f"- Event kind: `{identity['eventKind']}`",
        f"- Creation timestamp: {packet['creationTimestamp']}",
        "- Boundary: offline, deterministic, nontransmitting, and not a Codex interpretation.",
        "",
        "## Input File Hashes",
        "",
    ]
    for item in packet["inputFiles"]:
        lines.append(
            f"- `{item['role']}`: `{item['filename']}` — `{item['sha256']}` ({item['bytes']} bytes)"
        )
    for section_name, fields in packet["sections"].items():
        lines.extend(("", f"## {section_name.replace('_', ' ').title()}", ""))
        for field_name, field in fields.items():
            classification = field["classification"]
            if classification == "REVIEW_QUESTION":
                value = field["question"]
            elif classification == "MISSING":
                value = field["reason"]
            else:
                value = json.dumps(field.get("value"), sort_keys=True, ensure_ascii=True)
            lines.append(f"- **{field_name}** [{classification}]: {value}")
    lines.extend(
        (
            "",
            "## Safety Boundary",
            "",
            "This packet does not invoke Codex, contact a provider, operate a broker, advance a lifecycle, or alter source evidence.",
            "",
        )
    )
    return "\n".join(lines)


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_pair_once(
    json_path: Path,
    json_bytes: bytes,
    markdown_path: Path,
    markdown_bytes: bytes,
) -> bool:
    existing_json = json_path.read_bytes() if json_path.exists() else None
    existing_markdown = markdown_path.read_bytes() if markdown_path.exists() else None
    if existing_json is not None or existing_markdown is not None:
        if existing_json == json_bytes and existing_markdown == markdown_bytes:
            return True
        raise TerminalReviewPacketError(
            "Conflicting packet output already exists; write-once outputs were not changed."
        )
    created: list[Path] = []
    try:
        with json_path.open("xb") as stream:
            stream.write(json_bytes)
        created.append(json_path)
        with markdown_path.open("xb") as stream:
            stream.write(markdown_bytes)
        created.append(markdown_path)
    except OSError as exc:
        rollback_failures = []
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                rollback_failures.append(path.name)
        detail = (
            " Rollback could not remove: " + ", ".join(rollback_failures) + "."
            if rollback_failures
            else ""
        )
        raise TerminalReviewPacketError(
            "Packet output pair could not be created; newly written partial outputs were "
            "rolled back." + detail
        ) from exc
    return False


def _assert_sources_unchanged(initial_hashes: Mapping[Path, str]) -> None:
    changed = []
    for path, expected in initial_hashes.items():
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            actual = "UNREADABLE"
        if actual != expected:
            changed.append(path.name)
    if changed:
        raise TerminalReviewPacketError(
            "Source evidence changed during packet construction: " + ", ".join(sorted(changed))
        )


def _remove_new_output_pair(json_path: Path, markdown_path: Path) -> None:
    failures = []
    for path in (markdown_path, json_path):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            failures.append(path.name)
    if failures:
        raise TerminalReviewPacketError(
            "Source evidence changed after output creation, and newly written output cleanup "
            "failed for: " + ", ".join(failures) + "."
        )


def _redact_error(message: str) -> str:
    text = _SENSITIVE_VALUE.sub("[REDACTED]", message)
    text = re.sub(r"(?i)(account|token|secret|password)[^|\n]{0,120}", r"\1 [REDACTED]", text)
    return text[:1000]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one offline terminal Shadow review packet from explicit persisted evidence."
    )
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--decision-cycles-path", type=Path, required=True)
    parser.add_argument("--handoff-path", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--activation-path", type=Path, required=True)
    parser.add_argument("--selection-policy-path", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = TerminalReviewPacketRequest(
        event_id=args.event_id,
        output_dir=args.output_dir,
        state_path=args.state_path,
        decision_cycles_path=args.decision_cycles_path,
        handoff_path=args.handoff_path,
        report_path=args.report_path,
        activation_path=args.activation_path,
        selection_policy_path=args.selection_policy_path,
    )
    try:
        result = build_terminal_review_packet(request)
    except TerminalReviewPacketError as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED_CLOSED",
                    "eventId": args.event_id,
                    "error": _redact_error(str(exc)),
                    "sourceMutation": False,
                    "networkUsed": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
