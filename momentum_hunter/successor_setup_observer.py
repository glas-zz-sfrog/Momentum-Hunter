"""Prospective, outcome-blind research for successor intraday setups.

This module is deliberately offline. It reads explicit persisted evidence paths and
writes immutable research packets. It has no provider, account, risk, allocation,
broker, service, scheduler, Shadow, Paper, or production-store integration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping, Sequence

from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
)
from momentum_hunter.premarket_structure_research import (
    CANONICAL_SOURCE,
    EASTERN,
    MAX_ENTRY_EXTENSION_PCT,
    MIN_EXECUTION_RR,
    ResearchBar,
    aggregate_bars,
    classify_aggregate,
    classify_full_structure,
    load_research_bars,
)


SCHEMA_VERSION = 1
SAMPLE_ID = "successor-setup-research-20260813-v1"
PASS1_ENGINE_VERSION = "prospective-successor-setup-pass1-v1"
PASS2_ENGINE_VERSION = "prospective-successor-setup-pass2-v1"
SUMMARY_ENGINE_VERSION = "prospective-successor-setup-summary-v1"
RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
MAX_EVALUATED_CANDIDATES = 5
DECISION_CUTOFF = time(9, 35)
FORCED_FLAT = time(15, 55)
BENCHMARKS = ("SPY", "QQQ", "IWM")

ORIGINAL_UNTOUCHED = "ORIGINAL_UNTOUCHED"
ORIGINAL_TRIGGERED = "ORIGINAL_TRIGGERED"
ORIGINAL_MISSED = "ORIGINAL_MISSED"
ORIGINAL_FAILED = "ORIGINAL_FAILED"
INDETERMINATE = "INDETERMINATE"

ALLOW_AT_DECISION = "ALLOW_AT_DECISION"
ALLOW_PENDING_TRIGGER = "ALLOW_PENDING_TRIGGER"
BLOCK = "BLOCK"
ABSTAIN = "ABSTAIN"

UNTRIGGERED = "UNTRIGGERED"
TARGET_FIRST = "TARGET_FIRST"
STOP_FIRST = "STOP_FIRST"
TIMEOUT = "TIMEOUT"
INVALIDATED = "INVALIDATED"
AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
DATA_FAILURE = "DATA_FAILURE"

FROZEN_RULES: dict[str, Any] = {
    "researchSampleId": SAMPLE_ID,
    "maxEntryExtensionPct": MAX_ENTRY_EXTENSION_PCT,
    "minimumExecutionRewardRisk": MIN_EXECUTION_RR,
    "decisionCutoffEastern": "09:35:00",
    "forcedFlatEastern": "15:55:00",
    "earliestExpectedTrustedCoverageEastern": "07:00:00",
    "true0400To0700Path": "UNOBSERVED",
    "maximumEvaluatedCandidates": MAX_EVALUATED_CANDIDATES,
    "candidatePriority": "ASCENDING_CANONICAL_RANK_THEN_SYMBOL",
    "successorPriority": [CONTINUATION_BREAKOUT, RECLAIM, PULLBACK],
    "continuationDefinition": "SETUP_001_CLASSIFY_FULL_STRUCTURE_V1",
    "reclaimDefinition": (
        "ORIGINAL_LEVEL_CROSSED_THEN_COMPLETED_CLOSE_AT_OR_BELOW_LEVEL_THEN_"
        "COMPLETED_CLOSE_ABOVE_LEVEL"
    ),
    "pullbackDefinition": (
        "ORIGINAL_LEVEL_CROSSED_PREMARKET_LAST15_PULLBACK_OR_CONSOLIDATION_"
        "THEN_COMPLETED_OPENING_CLOSE_ABOVE_LAST15_HIGH"
    ),
    "targetRule": "TWO_R_FROM_FROZEN_STRUCTURAL_STOP",
    "outcomeOrdering": "ONE_MINUTE_OHLC_NO_INTRABAR_ORDER_ASSUMPTION",
    "productionSemantics": "UNCHANGED_CONTROL",
    "parameterTuning": "PROHIBITED_DURING_SAMPLE",
}
class SuccessorSetupResearchError(RuntimeError):
    """Raised when research evidence is incomplete, contradictory, or altered."""


def fingerprint_payload(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest().upper()


POLICY_FINGERPRINT = fingerprint_payload(FROZEN_RULES)


def packet_fingerprint(payload: Mapping[str, Any]) -> str:
    copy = dict(payload)
    if payload.get("pass") == "PASS_2_TERMINAL_OUTCOME":
        copy.pop("outcomeFingerprint", None)
    elif payload.get("engineVersion") == SUMMARY_ENGINE_VERSION:
        copy.pop("summaryFingerprint", None)
    elif "activationAuthorized" in payload:
        copy.pop("activationPlanFingerprint", None)
    elif payload.get("pass") == "PASS_1_OUTCOME_BLIND_DECISION":
        copy.pop("decisionFingerprint", None)
    elif "initialCounts" in payload:
        copy.pop("charterFingerprint", None)
    return fingerprint_payload(copy)


def create_sample_charter(*, created_at: str, output_path: Path) -> dict[str, Any]:
    """Create the immutable empty prospective sample identity."""

    _parse_datetime(created_at)
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "task": "ARGUS-SETUP-002",
        "sampleId": SAMPLE_ID,
        "createdAt": created_at,
        "status": "EMPTY_PENDING_FUTURE_ACTIVATION",
        "sampleOrigin": "PROSPECTIVE_ONLY",
        "setup001Treatment": "CASE_STUDY_EXCLUDED_FROM_PROSPECTIVE_DENOMINATOR",
        "researchQuestion": (
            "After an original setup is classified, does a distinct continuation, "
            "pullback, or reclaim setup form prospectively?"
        ),
        "frozenRules": FROZEN_RULES,
        "policyFingerprint": POLICY_FINGERPRINT,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "initialCounts": _empty_counts(),
        "checkpoints": [25, 50, 100],
        "checkpointRule": "REVIEW_WITHOUT_PARAMETER_TUNING_OR_EDGE_CLAIM",
    }
    payload["charterFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def build_pass_one(
    *,
    charter_path: Path,
    trade_plan_path: Path,
    capture_path: Path,
    minute_store_root: Path,
    observed_at: str,
    output_path: Path,
    paper_result_path: Path | None = None,
    maximum_evaluated_candidates: int = MAX_EVALUATED_CANDIDATES,
) -> dict[str, Any]:
    """Freeze an outcome-blind 09:35 ET research opinion for every candidate."""

    charter = _validated_charter(charter_path)
    if maximum_evaluated_candidates != MAX_EVALUATED_CANDIDATES:
        raise SuccessorSetupResearchError("The frozen provider bound cannot be changed.")
    observed = _parse_datetime(observed_at).astimezone(EASTERN)
    session_date = _report_session_date(_read_json(trade_plan_path))
    if observed.date().isoformat() != session_date or observed.time() < DECISION_CUTOFF:
        raise SuccessorSetupResearchError("Pass 1 observation time is outside its session/cutoff.")
    cutoff = datetime.combine(observed.date(), DECISION_CUTOFF, tzinfo=EASTERN)
    report = _read_json(trade_plan_path)
    capture = _read_json(capture_path)
    candidates = _candidate_rows(report)
    if not candidates:
        raise SuccessorSetupResearchError("Opening report has no candidate denominator.")
    paper = _safe_paper_baseline(_read_json(paper_result_path)) if paper_result_path else {}

    source_hashes = {
        "charter": _sha256_file(charter_path),
        "tradePlanReport": _sha256_file(trade_plan_path),
        "capture": _sha256_file(capture_path),
    }
    if paper_result_path:
        source_hashes["paperResult"] = _sha256_file(paper_result_path)
    market_context = _market_context(
        minute_store_root=minute_store_root,
        session_date=session_date,
        cutoff=cutoff,
        source_hashes=source_hashes,
    )

    results: list[dict[str, Any]] = []
    evaluated = 0
    for row in candidates:
        baseline = _baseline(row, paper, market_context)
        if evaluated >= maximum_evaluated_candidates:
            results.append(
                {
                    **baseline,
                    "evaluationStatus": "NOT_EVALUATED_PROVIDER_BOUND",
                    "researchOpinion": _research_opinion(
                        ABSTAIN, "NOT_EVALUATED_PROVIDER_BOUND", None
                    ),
                }
            )
            continue
        evaluated += 1
        symbol = baseline["symbol"]
        partition_path = minute_store_root / session_date / f"{symbol}.json"
        try:
            bars = load_research_bars(partition_path, expected_symbol=symbol)
            _validate_session_bars(bars, expected_date=session_date)
        except (OSError, SuccessorSetupResearchError, RuntimeError, ValueError) as exc:
            results.append(
                {
                    **baseline,
                    "evaluationStatus": "INSUFFICIENT_PREMARKET_HISTORY",
                    "evidenceFailure": _redacted_error(exc),
                    "researchOpinion": _research_opinion(
                        ABSTAIN, "INSUFFICIENT_PREMARKET_HISTORY", None
                    ),
                }
            )
            continue
        cutoff_bars = [bar for bar in bars if bar.timestamp < cutoff]
        source_hashes[f"cutoffMinuteEvidence:{symbol}"] = _bars_fingerprint(cutoff_bars)
        try:
            results.append(
                _evaluate_candidate(
                    row=row,
                    baseline=baseline,
                    bars=cutoff_bars,
                    observed_at=observed,
                    cutoff=cutoff,
                    source_path=partition_path,
                )
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            results.append(
                {
                    **baseline,
                    "evaluationStatus": "INSUFFICIENT_REQUIRED_PLAN_OR_LEVEL_EVIDENCE",
                    "evidenceFailure": _redacted_error(exc),
                    "researchOpinion": _research_opinion(
                        ABSTAIN, "INSUFFICIENT_REQUIRED_PLAN_OR_LEVEL_EVIDENCE", None
                    ),
                }
            )
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": PASS1_ENGINE_VERSION,
        "task": "ARGUS-SETUP-002",
        "pass": "PASS_1_OUTCOME_BLIND_DECISION",
        "sampleId": SAMPLE_ID,
        "charterFingerprint": charter["charterFingerprint"],
        "policyFingerprint": POLICY_FINGERPRINT,
        "sessionDate": session_date,
        "observedAt": observed.isoformat(),
        "evidenceCutoff": cutoff.isoformat(),
        "outcomeEvidenceInspected": False,
        "candidateDenominatorCount": len(candidates),
        "evaluatedCandidateCount": evaluated,
        "candidateOrdering": "ASCENDING_CANONICAL_RANK_THEN_SYMBOL",
        "captureIdentity": _capture_identity(report, capture),
        "marketContext": market_context,
        "candidates": results,
        "sourceHashes": dict(sorted(source_hashes.items())),
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "productionMutation": False,
        "limitations": [
            "Trusted history begins at the first returned Schwab bar, normally near 07:00 ET.",
            "The true 04:00-07:00 ET path remains unobserved.",
            "BAR_DERIVED_VWAP is not a provider-authoritative VWAP field.",
            "No verticality measurement has strategy-threshold authority.",
            "Research opinion cannot admit, rank, size, risk-review, or execute a candidate.",
        ],
    }
    payload["decisionFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def build_pass_two(
    *, decision_path: Path, minute_store_root: Path, finalized_at: str, output_path: Path
) -> dict[str, Any]:
    """Adjudicate later outcomes without altering the frozen Pass 1 opinion."""

    decision = _read_json(decision_path)
    _validate_decision(decision)
    cutoff = _parse_datetime(str(decision["evidenceCutoff"])).astimezone(EASTERN)
    session_date = str(decision["sessionDate"])
    finalized = _parse_datetime(finalized_at).astimezone(EASTERN)
    if finalized.date().isoformat() != session_date or finalized.time() < time(16, 0):
        raise SuccessorSetupResearchError(
            "Pass 2 requires an explicit same-session after-close finalization time."
        )
    outcomes: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for candidate in decision["candidates"]:
        symbol = str(candidate["symbol"])
        if candidate.get("evaluationStatus") == "NOT_EVALUATED_PROVIDER_BOUND":
            outcomes.append(_non_trade_outcome(candidate, [], "NOT_EVALUATED_PROVIDER_BOUND"))
            continue
        partition_path = minute_store_root / session_date / f"{symbol}.json"
        try:
            bars = load_research_bars(partition_path, expected_symbol=symbol)
            _validate_session_bars(bars, expected_date=session_date)
            cutoff_bars = [bar for bar in bars if bar.timestamp < cutoff]
            expected_cutoff_hash = decision["sourceHashes"].get(
                f"cutoffMinuteEvidence:{symbol}"
            )
            if expected_cutoff_hash and _bars_fingerprint(cutoff_bars) != expected_cutoff_hash:
                raise SuccessorSetupResearchError(
                    f"{symbol} cutoff evidence changed after Pass 1."
                )
            later = [
                bar
                for bar in bars
                if cutoff <= bar.timestamp
                and bar.timestamp.astimezone(EASTERN).time() <= FORCED_FLAT
            ]
            source_hashes[f"terminalMinuteEvidence:{symbol}"] = _bars_fingerprint(later)
            outcomes.append(_adjudicate(candidate, later))
        except (OSError, RuntimeError, ValueError) as exc:
            outcomes.append(
                {
                    "symbol": symbol,
                    "rank": candidate["rank"],
                    "frozenCandidateFingerprint": candidate.get("candidateFingerprint"),
                    "outcomeStatus": DATA_FAILURE,
                    "failure": _redacted_error(exc),
                    "hypotheticalTrade": False,
                }
            )

    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": PASS2_ENGINE_VERSION,
        "task": "ARGUS-SETUP-002",
        "pass": "PASS_2_TERMINAL_OUTCOME",
        "sampleId": SAMPLE_ID,
        "policyFingerprint": POLICY_FINGERPRINT,
        "sessionDate": session_date,
        "finalizedAt": finalized.isoformat(),
        "decisionFingerprint": decision["decisionFingerprint"],
        "decisionPacketSha256": _sha256_file(decision_path),
        "outcomeEvidenceInspected": True,
        "candidates": outcomes,
        "sourceHashes": dict(sorted(source_hashes.items())),
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "interpretationRule": (
            "Later behavior adjudicates the frozen opinion and cannot alter Pass 1."
        ),
    }
    payload["outcomeFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def build_sample_summary(
    *, charter_path: Path, pass_one_paths: Sequence[Path], pass_two_paths: Sequence[Path], output_path: Path
) -> dict[str, Any]:
    """Build a deterministic aggregate from explicit immutable packet paths."""

    charter = _validated_charter(charter_path)
    decisions = [_read_json(path) for path in pass_one_paths]
    outcomes = [_read_json(path) for path in pass_two_paths]
    for decision in decisions:
        _validate_decision(decision)
    for outcome in outcomes:
        if outcome.get("sampleId") != SAMPLE_ID or outcome.get("outcomeFingerprint") != packet_fingerprint(outcome):
            raise SuccessorSetupResearchError("Invalid Pass 2 packet in sample summary.")
    if len({item["sessionDate"] for item in decisions}) != len(decisions):
        raise SuccessorSetupResearchError("Duplicate Pass 1 session in sample summary.")
    if len({item["sessionDate"] for item in outcomes}) != len(outcomes):
        raise SuccessorSetupResearchError("Duplicate Pass 2 session in sample summary.")
    decision_fingerprints = {
        item["sessionDate"]: item["decisionFingerprint"] for item in decisions
    }
    for outcome in outcomes:
        if decision_fingerprints.get(outcome["sessionDate"]) != outcome.get("decisionFingerprint"):
            raise SuccessorSetupResearchError(
                "Pass 2 is not bound to the exact same-session Pass 1 packet."
            )

    counts = _empty_counts()
    families: dict[str, int] = {}
    ranks: dict[str, int] = {}
    models = {"A_ALLOW": 0, "B_ALLOW": 0, "C_ALLOW": 0}
    for decision in decisions:
        counts["tradingSessionsObserved"] += 1
        counts["openingCandidatesObserved"] += len(decision["candidates"])
        for candidate in decision["candidates"]:
            ranks[str(candidate["rank"])] = ranks.get(str(candidate["rank"]), 0) + 1
            if candidate.get("evaluationStatus") == "EVALUATED":
                counts["candidatesFullyEvaluated"] += 1
            elif str(candidate.get("evaluationStatus", "")).startswith("INSUFFICIENT"):
                counts["evidenceFailures"] += 1
            if candidate.get("originalSetup", {}).get("lifecycleStatus") == ORIGINAL_MISSED:
                counts["originalSetupsMissed"] += 1
            proposal = candidate.get("successorSetup")
            if proposal and proposal.get("setupId"):
                counts["successorSetupsProposed"] += 1
                family = str(proposal["family"])
                families[family] = families.get(family, 0) + 1
            elif candidate.get("evaluationStatus") == "EVALUATED":
                counts["noNewStructureObservations"] += 1
            for key, bucket in (("modelA", "A_ALLOW"), ("modelB", "B_ALLOW"), ("modelC", "C_ALLOW")):
                if str(candidate.get("models", {}).get(key, {}).get("opinion", "")).startswith("ALLOW"):
                    models[bucket] += 1
    for outcome in outcomes:
        for candidate in outcome["candidates"]:
            status = candidate.get("outcomeStatus")
            mapping = {
                UNTRIGGERED: "untriggeredProposals",
                TARGET_FIRST: "targetFirst",
                STOP_FIRST: "stopFirst",
                TIMEOUT: "timeout",
                INVALIDATED: "invalidatedProposals",
                AMBIGUOUS_SAME_BAR: "ambiguous",
                DATA_FAILURE: "evidenceFailures",
            }
            if status in mapping:
                counts[mapping[status]] += 1
            if candidate.get("triggerAt"):
                counts["successorSetupsTriggered"] += 1

    completed = counts["candidatesFullyEvaluated"]
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": SUMMARY_ENGINE_VERSION,
        "sampleId": SAMPLE_ID,
        "charterFingerprint": charter["charterFingerprint"],
        "policyFingerprint": POLICY_FINGERPRINT,
        "counts": counts,
        "setupFamilyDistribution": dict(sorted(families.items())),
        "rankDistribution": dict(sorted(ranks.items(), key=lambda item: int(item[0]))),
        "modelComparisonCounts": models,
        "checkpoints": [
            {"candidateCount": value, "status": "REACHED" if completed >= value else "PENDING"}
            for value in (25, 50, 100)
        ],
        "interpretation": "NO_EDGE_CLAIM_NO_PARAMETER_TUNING",
        "inputHashes": {
            "charter": _sha256_file(charter_path),
            **{f"pass1:{path.name}": _sha256_file(path) for path in pass_one_paths},
            **{f"pass2:{path.name}": _sha256_file(path) for path in pass_two_paths},
        },
    }
    payload["summaryFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def build_dormant_activation_plan(*, created_at: str, output_path: Path) -> dict[str, Any]:
    """Describe a future unattended lifecycle without installing or activating it."""

    _parse_datetime(created_at)
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "task": "ARGUS-SETUP-002",
        "createdAt": created_at,
        "status": "NOT_INSTALLED",
        "activationAuthorized": False,
        "earliestActivationGate": "AFTER_AUGUST_14_OPERATIONAL_EVIDENCE_IS_TERMINAL_AND_PRESERVED",
        "lifecycle": [
            "OPENING_CAPTURE_TERMINAL",
            "PASS_1_WRITE_ONCE",
            "WAIT_UNTIL_AFTER_REGULAR_CLOSE",
            "PASS_2_WRITE_ONCE",
        ],
        "finitePolicy": {"pass1TimeoutMinutes": 10, "pass2TimeoutMinutes": 15, "retries": 0},
        "failureIsolation": (
            "RESEARCH_FAILURE_CANNOT_CHANGE_OPENING_OR_PAPER_STATUS_AND_CANNOT_BLOCK_PRODUCTION"
        ),
        "requiredFutureProof": [
            "EXACT_RUNTIME_PIN",
            "DISTINCT_RESEARCH_OUTPUT_ROOT",
            "NO_LATE_RECONSTRUCTION_OUTSIDE_EXPLICIT_CUTOFF",
            "NO_SERVICE_OR_PRODUCTION_STORE_MUTATION",
        ],
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
    }
    payload["activationPlanFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def _evaluate_candidate(
    *,
    row: Mapping[str, Any],
    baseline: Mapping[str, Any],
    bars: Sequence[ResearchBar],
    observed_at: datetime,
    cutoff: datetime,
    source_path: Path,
) -> dict[str, Any]:
    symbol = str(baseline["symbol"])
    premarket = _between(bars, time(4, 0), time(9, 30))
    last15 = _between(bars, time(9, 15), time(9, 30))
    opening = _between(bars, time(9, 30), DECISION_CUTOFF)
    if not premarket:
        return {
            **baseline,
            "evaluationStatus": "INSUFFICIENT_PREMARKET_HISTORY",
            "researchOpinion": _research_opinion(ABSTAIN, "INSUFFICIENT_PREMARKET_HISTORY", None),
        }
    if len(last15) != 15:
        return {
            **baseline,
            "evaluationStatus": "INSUFFICIENT_LAST15_STRUCTURE_EVIDENCE",
            "researchOpinion": _research_opinion(ABSTAIN, "INSUFFICIENT_LAST15_STRUCTURE_EVIDENCE", None),
        }
    if len(opening) != 5:
        return {
            **baseline,
            "evaluationStatus": "INSUFFICIENT_OPENING_STRUCTURE_EVIDENCE",
            "researchOpinion": _research_opinion(ABSTAIN, "INSUFFICIENT_OPENING_STRUCTURE_EVIDENCE", None),
        }

    plan = _plan_fields(row)
    quote = _quote_fields(row)
    levels = _level_fields(row)
    original = _original_lifecycle(
        bars=premarket + opening,
        trigger=plan["entry"],
        stop=plan["stop"],
        ask=quote["ask"],
    )
    model_a = _proposal(
        symbol=symbol,
        family=OPENING_BREAKOUT,
        trigger=plan["entry"],
        stop=plan["stop"],
        ask=quote["ask"],
        predecessor=plan["setupFingerprint"],
        evidence_ids=[plan["setupFingerprint"]],
        chronology="CURRENT_MH_ORIGINAL_LEVEL_ONLY",
        permit_new_setup=False,
    )
    model_a["lifecycleStatus"] = original["lifecycleStatus"]
    l15 = aggregate_bars(last15)
    model_b = _proposal(
        symbol=symbol,
        family=CONTINUATION_BREAKOUT,
        trigger=float(l15["high"]),
        stop=float(l15["low"]),
        ask=quote["ask"],
        predecessor=plan["setupFingerprint"],
        evidence_ids=[bar.identity for bar in last15],
        chronology="PRIOR_15_MINUTE_DOMINANT_FEATURE_ONLY",
        permit_new_setup=True,
    )
    model_b["warning"] = "MODEL_B_IS_A_COMPARISON_FEATURE_NOT_PROVEN_CHRONOLOGY"
    model_c = _successor_model(
        symbol=symbol,
        original=original,
        plan=plan,
        quote=quote,
        atr=levels["atr"],
        premarket=premarket,
        last15=last15,
        opening=opening,
    )

    pm = aggregate_bars(premarket)
    op = aggregate_bars(opening)
    basis = _data_basis(source_path, bars)
    candidate: dict[str, Any] = {
        **baseline,
        "evaluationStatus": "EVALUATED",
        "observedAt": observed_at.isoformat(),
        "evidenceCutoff": cutoff.isoformat(),
        "outcomeEvidenceInspected": False,
        "sourceEvidence": {
            "provider": CANONICAL_SOURCE,
            "cutoffBarEvidenceFingerprint": _bars_fingerprint(bars),
            "earliestTrustedBar": min(bar.timestamp for bar in bars).isoformat(),
            "premarketCoverageStart": min(bar.timestamp for bar in premarket).isoformat(),
            "true0400To0700Path": "UNOBSERVED",
            **basis,
        },
        "priorReference": levels,
        "originalSetup": {**plan, **original},
        "premarket": {
            **pm,
            "classification": classify_aggregate(pm),
            "vwapKind": "BAR_DERIVED_VWAP",
            "gapFromPriorClosePct": _pct(pm["open"], levels["priorClose"]),
            "distanceFromOriginalTriggerPct": _pct(quote["ask"], plan["entry"]),
            "distanceFromPremarketHighPct": _pct(quote["ask"], pm["high"]),
            "retracementFromPremarketHighPct": _pct(pm["close"], pm["high"]),
        },
        "last15": {
            **l15,
            "classification": classify_aggregate(l15),
            "locationVsPremarketHighPct": _pct(l15["close"], pm["high"]),
            "locationVsPremarketVwapPct": _pct(l15["close"], pm["vwapApprox"]),
        },
        "openingRange": {
            **op,
            "classification": classify_aggregate(op),
            "vwapKind": "BAR_DERIVED_VWAP",
            "locationVsPremarketHighPct": _pct(op["close"], pm["high"]),
            "locationVsPremarketLowPct": _pct(op["close"], pm["low"]),
            "locationVsPremarketVwapPct": _pct(op["close"], pm["vwapApprox"]),
            "acceptedAbovePremarketHigh": op["close"] > pm["high"],
            "rejectedPremarketHigh": op["high"] > pm["high"] and op["close"] < pm["high"],
        },
        "decisionQuote": quote,
        "verticalityFeatures": _verticality(
            bars=bars,
            premarket=premarket,
            opening=opening,
            quote=quote,
            prior_close=levels["priorClose"],
            atr=levels["atr"],
            structural_stop=(model_c.get("stop") or plan["stop"]),
            target=(model_c.get("targets") or [plan["target1"]])[0],
        ),
        "models": {"modelA": model_a, "modelB": model_b, "modelC": model_c},
        "successorSetup": model_c if model_c.get("setupId") else None,
        "researchOpinion": _research_opinion(
            str(model_c.get("opinion", BLOCK)),
            str(model_c.get("reason", "NO_NEW_STRUCTURE")),
            model_c.get("setupId"),
        ),
    }
    candidate["candidateFingerprint"] = fingerprint_payload(candidate)
    return candidate


def _successor_model(
    *,
    symbol: str,
    original: Mapping[str, Any],
    plan: Mapping[str, Any],
    quote: Mapping[str, Any],
    atr: float,
    premarket: Sequence[ResearchBar],
    last15: Sequence[ResearchBar],
    opening: Sequence[ResearchBar],
) -> dict[str, Any]:
    if original["lifecycleStatus"] not in {ORIGINAL_MISSED, ORIGINAL_FAILED}:
        return _no_structure("ORIGINAL_SETUP_NOT_MISSED_OR_FAILED")
    setup1 = classify_full_structure(
        symbol=symbol,
        original_entry=float(plan["entry"]),
        original_stop=float(plan["stop"]),
        original_target=float(plan["target1"]),
        original_setup_fingerprint=str(plan["setupFingerprint"]),
        ask=float(quote["ask"]),
        atr=atr,
        premarket=premarket,
        last_15=last15,
        opening=opening,
    )
    continuation = _continuation_candidate(
        symbol=symbol,
        predecessor=str(plan["setupFingerprint"]),
        ask=float(quote["ask"]),
        atr=atr,
        premarket=premarket,
        last15=last15,
        opening=opening,
    )
    if setup1.get("newSetup") or continuation:
        return continuation or _normalize_setup1(setup1)
    reclaim = _reclaim_candidate(
        symbol=symbol,
        predecessor=str(plan["setupFingerprint"]),
        original_trigger=float(plan["entry"]),
        ask=float(quote["ask"]),
        bars=list(premarket) + list(opening),
    )
    if reclaim:
        return reclaim
    pullback = _pullback_candidate(
        symbol=symbol,
        predecessor=str(plan["setupFingerprint"]),
        ask=float(quote["ask"]),
        premarket=premarket,
        last15=last15,
        opening=opening,
    )
    return pullback or _no_structure("NO_NEW_DEFENSIBLE_STRUCTURE_BY_DECISION")


def _continuation_candidate(
    *, symbol: str, predecessor: str, ask: float, atr: float,
    premarket: Sequence[ResearchBar], last15: Sequence[ResearchBar], opening: Sequence[ResearchBar]
) -> dict[str, Any] | None:
    pm = aggregate_bars(premarket)
    l15 = aggregate_bars(last15)
    op = aggregate_bars(opening)
    high_bar = max(premarket, key=lambda bar: (bar.high, -bar.timestamp.timestamp()))
    after_high = [bar for bar in premarket if bar.timestamp > high_bar.timestamp]
    pullback_depth = high_bar.high - min((bar.low for bar in after_high), default=high_bar.high)
    opening_high_bar = max(opening, key=lambda bar: (bar.high, -bar.timestamp.timestamp()))
    chronology = (
        high_bar.timestamp.astimezone(EASTERN).time() < time(9, 15)
        and pullback_depth >= 0.15 * atr
        and l15["close"] < pm["high"]
        and op["high"] >= pm["high"]
        and any(bar.timestamp > opening_high_bar.timestamp for bar in opening)
    )
    if not chronology:
        return None
    return _proposal(
        symbol=symbol,
        family=CONTINUATION_BREAKOUT,
        trigger=float(op["high"]),
        stop=max(float(l15["low"]), float(op["low"])),
        ask=ask,
        predecessor=predecessor,
        evidence_ids=[bar.identity for bar in list(premarket) + list(opening)],
        chronology="PREMARKET_IMPULSE_PULLBACK_THEN_COMPLETED_OPENING_RANGE_BREAK",
        permit_new_setup=True,
    )


def _reclaim_candidate(
    *, symbol: str, predecessor: str, original_trigger: float, ask: float, bars: Sequence[ResearchBar]
) -> dict[str, Any] | None:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    crossed = False
    lost_index: int | None = None
    for index, bar in enumerate(ordered):
        crossed = crossed or bar.high >= original_trigger
        if crossed and bar.close <= original_trigger:
            lost_index = index
        if lost_index is not None and index > lost_index and bar.close > original_trigger:
            structure = ordered[lost_index : index + 1]
            return _proposal(
                symbol=symbol,
                family=RECLAIM,
                trigger=max(original_trigger, bar.high),
                stop=min(item.low for item in structure),
                ask=ask,
                predecessor=predecessor,
                evidence_ids=[item.identity for item in structure],
                chronology="ORIGINAL_TRIGGER_LOST_THEN_COMPLETED_BAR_RECLAIMED",
                permit_new_setup=True,
            )
    return None


def _pullback_candidate(
    *, symbol: str, predecessor: str, ask: float,
    premarket: Sequence[ResearchBar], last15: Sequence[ResearchBar], opening: Sequence[ResearchBar]
) -> dict[str, Any] | None:
    l15 = aggregate_bars(last15)
    op = aggregate_bars(opening)
    if classify_aggregate(l15) not in {"PULLBACK", "CONSOLIDATION"}:
        return None
    if op["close"] <= l15["high"]:
        return None
    return _proposal(
        symbol=symbol,
        family=PULLBACK,
        trigger=float(l15["high"]),
        stop=min(float(l15["low"]), float(op["low"])),
        ask=ask,
        predecessor=predecessor,
        evidence_ids=[bar.identity for bar in list(last15) + list(opening)],
        chronology="COMPLETED_LAST15_PULLBACK_THEN_OPENING_CLOSE_ABOVE_LOCAL_HIGH",
        permit_new_setup=True,
    )


def _proposal(
    *, symbol: str, family: str, trigger: float, stop: float, ask: float,
    predecessor: str, evidence_ids: Sequence[str], chronology: str, permit_new_setup: bool
) -> dict[str, Any]:
    risk = trigger - stop
    if risk <= 0:
        return _no_structure("STRUCTURAL_STOP_NOT_BELOW_TRIGGER")
    target = trigger + 2.0 * risk
    extension = _pct(ask, trigger)
    evaluation_entry = trigger if ask < trigger else ask
    rr = _execution_rr(evaluation_entry, stop, target)
    if not permit_new_setup:
        opinion = BLOCK
        reason = "BASELINE_MODEL_NOT_A_SUCCESSOR_OPINION"
    elif ask < trigger and rr >= MIN_EXECUTION_RR:
        opinion = ALLOW_PENDING_TRIGGER
        reason = "FROZEN_PENDING_SUCCESSOR_TRIGGER"
    elif extension > MAX_ENTRY_EXTENSION_PCT:
        opinion = BLOCK
        reason = "SUCCESSOR_ENTRY_EXTENSION_EXCEEDS_0_25_PCT"
    elif rr < MIN_EXECUTION_RR:
        opinion = BLOCK
        reason = "EXECUTION_REWARD_RISK_BELOW_1_5"
    else:
        opinion = ALLOW_AT_DECISION
        reason = "FROZEN_SUCCESSOR_POLICY_PASSES"
    setup_basis = {
        "sampleId": SAMPLE_ID,
        "symbol": symbol,
        "family": family,
        "predecessor": predecessor,
        "trigger": round(trigger, 6),
        "stop": round(stop, 6),
        "target": round(target, 6),
        "chronology": chronology,
        "evidenceIds": sorted(set(evidence_ids)),
        "policyFingerprint": POLICY_FINGERPRINT,
    }
    return {
        "family": family,
        "setupId": fingerprint_payload(setup_basis),
        "predecessorSetupId": predecessor,
        "predecessorRelationship": "DISTINCT_SUCCESSOR_DOES_NOT_REWRITE_ORIGINAL",
        "trigger": round(trigger, 6),
        "stop": round(stop, 6),
        "targets": [round(target, 6)],
        "entryBasis": "DECISION_ASK" if ask >= trigger else "HYPOTHETICAL_TRIGGER_PRICE",
        "evaluationEntry": round(evaluation_entry, 6),
        "executionRewardRisk": rr,
        "extensionFromNewTriggerPct": round(extension, 6),
        "chronology": chronology,
        "evidenceIds": sorted(set(evidence_ids)),
        "researchEngineVersion": PASS1_ENGINE_VERSION,
        "policyFingerprint": POLICY_FINGERPRINT,
        "opinion": opinion,
        "reason": reason,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
    }


def _normalize_setup1(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["predecessorSetupId"] = result.pop("predecessorSetupFingerprint")
    result["predecessorRelationship"] = "DISTINCT_SUCCESSOR_DOES_NOT_REWRITE_ORIGINAL"
    result["evaluationEntry"] = None
    result["entryBasis"] = "DECISION_ASK"
    result["extensionFromNewTriggerPct"] = result.pop("extensionPct")
    result["opinion"] = ALLOW_AT_DECISION
    result["reason"] = "SETUP_001_FROZEN_CONTINUATION_RULE_PASSES"
    result["researchEngineVersion"] = PASS1_ENGINE_VERSION
    result["policyFingerprint"] = POLICY_FINGERPRINT
    result["authority"] = RESEARCH_ONLY
    result["executionAuthority"] = EXECUTION_AUTHORITY
    return result


def _no_structure(reason: str) -> dict[str, Any]:
    return {
        "family": "NO_NEW_STRUCTURE",
        "setupId": None,
        "predecessorSetupId": None,
        "trigger": None,
        "stop": None,
        "targets": [],
        "executionRewardRisk": None,
        "extensionFromNewTriggerPct": None,
        "opinion": BLOCK,
        "reason": reason,
        "researchEngineVersion": PASS1_ENGINE_VERSION,
        "policyFingerprint": POLICY_FINGERPRINT,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
    }


def _original_lifecycle(
    *, bars: Sequence[ResearchBar], trigger: float, stop: float, ask: float
) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    first = next((index for index, bar in enumerate(ordered) if bar.high >= trigger), None)
    if first is None:
        return {"lifecycleStatus": ORIGINAL_UNTOUCHED, "firstTriggerAt": None, "failureAt": None}
    failure = next((bar for bar in ordered[first:] if bar.low <= stop), None)
    if failure:
        status = ORIGINAL_FAILED
    elif _pct(ask, trigger) > MAX_ENTRY_EXTENSION_PCT:
        status = ORIGINAL_MISSED
    else:
        status = ORIGINAL_TRIGGERED
    return {
        "lifecycleStatus": status,
        "firstTriggerAt": ordered[first].timestamp.isoformat(),
        "crossMayPredateTrustedCoverage": first == 0 and ordered[first].open > trigger,
        "failureAt": failure.timestamp.isoformat() if failure else None,
        "immutableOriginal": True,
    }


def _adjudicate(candidate: Mapping[str, Any], bars: Sequence[ResearchBar]) -> dict[str, Any]:
    opinion = candidate.get("researchOpinion", {})
    successor = candidate.get("successorSetup")
    if not successor or not str(opinion.get("decision", "")).startswith("ALLOW"):
        return _non_trade_outcome(candidate, bars, str(opinion.get("reason", "NO_NEW_STRUCTURE")))
    if not bars:
        return {
            "symbol": candidate["symbol"],
            "rank": candidate["rank"],
            "frozenCandidateFingerprint": candidate["candidateFingerprint"],
            "setupId": successor["setupId"],
            "outcomeStatus": DATA_FAILURE,
            "hypotheticalTrade": False,
            "reason": "NO_POST_CUTOFF_BARS",
        }
    trigger = float(successor["trigger"])
    stop = float(successor["stop"])
    target = float(successor["targets"][0])
    decision = str(opinion["decision"])
    trigger_index: int | None = None
    trigger_at: datetime | None = None
    entry = float(successor["evaluationEntry"])
    if decision == ALLOW_AT_DECISION:
        trigger_index = 0
        trigger_at = _parse_datetime(str(candidate["observedAt"])).astimezone(EASTERN)
    else:
        for index, bar in enumerate(bars):
            if bar.low <= stop and bar.high < trigger:
                return _terminal_result(candidate, successor, INVALIDATED, None, bar.timestamp, [], entry)
            if bar.high >= trigger:
                trigger_index = index
                trigger_at = bar.timestamp
                entry = trigger
                break
        if trigger_index is None:
            if not _has_forced_flat_horizon(bars):
                result = _terminal_result(
                    candidate,
                    successor,
                    DATA_FAILURE,
                    None,
                    bars[-1].timestamp,
                    [],
                    entry,
                )
                result["reason"] = "INCOMPLETE_OUTCOME_HORIZON_BEFORE_15_55_ET"
                return result
            return _terminal_result(candidate, successor, UNTRIGGERED, None, bars[-1].timestamp, [], entry)

    lifecycle = list(bars[trigger_index:])
    terminal_status = TIMEOUT
    terminal_at = lifecycle[-1].timestamp
    used: list[ResearchBar] = []
    target_at = None
    stop_at = None
    for index, bar in enumerate(lifecycle):
        used.append(bar)
        target_hit = bar.high >= target
        stop_hit = bar.low <= stop
        if index == 0 and decision == ALLOW_PENDING_TRIGGER and stop_hit:
            terminal_status = AMBIGUOUS_SAME_BAR
            terminal_at = bar.timestamp
            stop_at = bar.timestamp
            target_at = bar.timestamp if target_hit else None
            break
        if target_hit and stop_hit:
            terminal_status = AMBIGUOUS_SAME_BAR
            terminal_at = bar.timestamp
            target_at = stop_at = bar.timestamp
            break
        if target_hit:
            terminal_status = TARGET_FIRST
            terminal_at = target_at = bar.timestamp
            break
        if stop_hit:
            terminal_status = STOP_FIRST
            terminal_at = stop_at = bar.timestamp
            break
    if terminal_status == TIMEOUT and not _has_forced_flat_horizon(lifecycle):
        terminal_status = DATA_FAILURE
    result = _terminal_result(candidate, successor, terminal_status, trigger_at, terminal_at, used, entry)
    result["targetAt"] = target_at.isoformat() if target_at else None
    result["stopAt"] = stop_at.isoformat() if stop_at else None
    result["timeToTargetMinutes"] = _minutes(trigger_at, target_at) if target_at else None
    result["timeToStopMinutes"] = _minutes(trigger_at, stop_at) if stop_at else None
    if terminal_status == DATA_FAILURE:
        result["reason"] = "INCOMPLETE_OUTCOME_HORIZON_BEFORE_15_55_ET"
    return result


def _terminal_result(
    candidate: Mapping[str, Any], successor: Mapping[str, Any], status: str,
    trigger_at: datetime | None, terminal_at: datetime, bars: Sequence[ResearchBar], entry: float
) -> dict[str, Any]:
    exact_excursions = status not in {AMBIGUOUS_SAME_BAR, DATA_FAILURE, UNTRIGGERED, INVALIDATED}
    pending_trigger = successor.get("entryBasis") == "HYPOTHETICAL_TRIGGER_PRICE"
    favorable_bars = list(bars)
    adverse_bars = list(bars[1:]) if pending_trigger and bars else list(bars)
    terminal_bar_excluded = status in {TARGET_FIRST, STOP_FIRST} and bool(bars)
    if terminal_bar_excluded:
        favorable_bars = favorable_bars[:-1]
        adverse_bars = adverse_bars[:-1] if adverse_bars else []

    high_bar = max(favorable_bars, key=lambda item: item.high) if favorable_bars else None
    low_bar = min(adverse_bars, key=lambda item: item.low) if adverse_bars else None
    mfe = max(0.0, high_bar.high - entry) if high_bar else 0.0
    mae = min(0.0, low_bar.low - entry) if low_bar else 0.0
    mfe_at = high_bar.timestamp if high_bar and high_bar.high > entry else trigger_at
    mae_at = low_bar.timestamp if low_bar and low_bar.low < entry else trigger_at
    if status == TARGET_FIRST:
        mfe = float(successor["targets"][0]) - entry
        mfe_at = terminal_at
    elif status == STOP_FIRST:
        mae = float(successor["stop"]) - entry
        mae_at = terminal_at
    if not exact_excursions:
        mfe = mae = None
        mfe_at = mae_at = None
    return {
        "symbol": candidate["symbol"],
        "rank": candidate["rank"],
        "frozenCandidateFingerprint": candidate["candidateFingerprint"],
        "setupId": successor["setupId"],
        "outcomeStatus": status,
        "hypotheticalTrade": trigger_at is not None,
        "entry": entry if trigger_at else None,
        "triggerAt": trigger_at.isoformat() if trigger_at else None,
        "terminalAt": terminal_at.isoformat(),
        "mfe": round(mfe, 6) if mfe is not None else None,
        "mae": round(mae, 6) if mae is not None else None,
        "mfePct": round((mfe / entry) * 100.0, 6) if mfe is not None else None,
        "maePct": round((mae / entry) * 100.0, 6) if mae is not None else None,
        "timeToMfeMinutes": _minutes(trigger_at, mfe_at) if trigger_at and mfe_at else None,
        "timeToMaeMinutes": _minutes(trigger_at, mae_at) if trigger_at and mae_at else None,
        "durationMinutes": _minutes(trigger_at, terminal_at) if trigger_at else None,
        "firstTerminalEvent": status,
        "excursionWindowEndsAtTerminal": True,
        "excursionMeasurementStatus": (
            "EXACT_TO_TERMINAL_WITH_TERMINAL_BAR_OPPOSING_EXTREME_EXCLUDED"
            if exact_excursions and terminal_bar_excluded
            else "EXACT_TO_OBSERVED_TIMEOUT"
            if exact_excursions
            else "UNAVAILABLE_INTRABAR_OR_INCOMPLETE_LIFECYCLE"
        ),
        "triggerBarAdverseExcursionExcluded": pending_trigger and bool(bars),
    }


def _non_trade_outcome(
    candidate: Mapping[str, Any], bars: Sequence[ResearchBar], reason: str
) -> dict[str, Any]:
    observation = {
        "classification": "POST_DECISION_COUNTERFACTUAL_OBSERVATION_NOT_A_TRADE",
        "lastObservedAt": bars[-1].timestamp.isoformat() if bars else None,
        "maximumHigh": max((bar.high for bar in bars), default=None),
        "minimumLow": min((bar.low for bar in bars), default=None),
        "laterBehaviorCannotAlterPass1": True,
    }
    provider_bound = reason == "NOT_EVALUATED_PROVIDER_BOUND"
    missing_required_outcome = not provider_bound and not _has_forced_flat_horizon(bars)
    return {
        "symbol": candidate["symbol"],
        "rank": candidate["rank"],
        "frozenCandidateFingerprint": candidate.get("candidateFingerprint"),
        "setupId": None,
        "outcomeStatus": DATA_FAILURE if missing_required_outcome else "NO_HYPOTHETICAL_TRADE",
        "hypotheticalTrade": False,
        "frozenReason": reason,
        "postDecisionObservation": observation,
        "reason": (
            "INCOMPLETE_COUNTERFACTUAL_HORIZON_BEFORE_15_55_ET"
            if missing_required_outcome
            else None
        ),
    }


def _baseline(
    row: Mapping[str, Any], paper: Mapping[str, Any], market_context: Mapping[str, Any]
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    rank = int(row["rank"])
    trade = row.get("trade_plan") if isinstance(row.get("trade_plan"), Mapping) else {}
    readiness = trade.get("readiness") if isinstance(trade.get("readiness"), Mapping) else {}
    paper_item = paper.get("evaluations", {}).get(symbol, {})
    company = row.get("company_profile") if isinstance(row.get("company_profile"), Mapping) else {}
    market = row.get("market_data") if isinstance(row.get("market_data"), Mapping) else {}
    sector = row.get("sector") or company.get("sector") or market.get("sector")
    return {
        "symbol": symbol,
        "rank": rank,
        "candidateDirection": "LONG",
        "marketDirectionAgreement": _market_direction_agreement(market_context),
        "sectorContext": {
            "sector": sector,
            "status": "AVAILABLE" if sector else "UNAVAILABLE",
            "authority": "PRESERVED_RESEARCH_COVARIATE_ONLY",
        },
        "baseline": {
            "candidateAdmitted": True,
            "originalSetupFamily": str(trade.get("setup_family") or OPENING_BREAKOUT),
            "originalSetupFingerprint": str(
                (trade.get("setup_evidence") or {}).get("fingerprint") or f"UNAVAILABLE:{symbol}"
            ),
            "productionTradePlanReady": readiness.get("ready"),
            "productionBlockingReasons": list(trade.get("blocking_reasons") or []),
            "paperEvaluated": paper_item.get("evaluated", False),
            "paperEligible": paper_item.get("eligible"),
            "paperBlockingReasons": paper_item.get("blockers", []),
            "paperDecisionClassification": paper.get("classification"),
            "controlPreserved": True,
        },
    }


def _safe_paper_baseline(payload: Mapping[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") if isinstance(payload.get("decision"), Mapping) else payload
    evaluations: dict[str, Any] = {}
    for item in decision.get("candidateEvaluations", []):
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if symbol:
            evaluations[symbol] = {
                "evaluated": True,
                "eligible": item.get("eligible"),
                "blockers": list(item.get("blockers") or []),
            }
    return {"classification": decision.get("classification"), "evaluations": evaluations}


def _plan_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    plan = row.get("trade_plan")
    if not isinstance(plan, Mapping):
        raise SuccessorSetupResearchError(f"{row.get('symbol')} has no TradePlan.")
    setup = plan.get("setup_evidence") if isinstance(plan.get("setup_evidence"), Mapping) else {}
    return {
        "family": str(plan.get("setup_family") or OPENING_BREAKOUT),
        "entry": float(plan["bullish_entry"]),
        "stop": float(plan["bullish_stop"]),
        "target1": float(plan["bullish_target_1"]),
        "setupFingerprint": str(setup.get("fingerprint") or f"UNAVAILABLE:{row.get('symbol')}"),
    }


def _quote_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    market = row.get("market_data")
    if not isinstance(market, Mapping):
        raise SuccessorSetupResearchError(f"{row.get('symbol')} has no market data.")
    provenance = (((row.get("market_tape") or {}).get("field_provenance") or {}).get("current_ask") or {})
    return {
        "bid": float(market["current_bid"]),
        "ask": float(market["current_ask"]),
        "spreadPct": float(market.get("spread_percent") or 0.0),
        "source": provenance.get("source"),
        "providerTimestamp": provenance.get("provider_timestamp"),
        "receiptTimestamp": provenance.get("local_receipt_timestamp"),
    }


def _level_fields(row: Mapping[str, Any]) -> dict[str, float]:
    levels = row.get("technical_levels")
    if not isinstance(levels, Mapping):
        raise SuccessorSetupResearchError(f"{row.get('symbol')} has no technical levels.")
    return {
        "priorClose": float(levels["previous_day_close"]),
        "priorHigh": float(levels["previous_day_high"]),
        "priorLow": float(levels["previous_day_low"]),
        "atr": float(levels["atr"]),
    }


def _verticality(
    *, bars: Sequence[ResearchBar], premarket: Sequence[ResearchBar], opening: Sequence[ResearchBar],
    quote: Mapping[str, Any], prior_close: float, atr: float, structural_stop: float,
    target: float
) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    pm = aggregate_bars(premarket)
    op = aggregate_bars(opening)
    ask = float(quote["ask"])
    running_high = ordered[0].high
    pullbacks: list[float] = []
    consecutive = maximum_consecutive = 0
    last_pullback_at = None
    material_pullback_count = 0
    in_material_pullback = False
    higher_lows = 0
    lower_highs = 0
    previous = None
    for bar in ordered:
        running_high = max(running_high, bar.high)
        depth = running_high - bar.low
        if depth > 0:
            pullbacks.append(depth)
            if depth >= 0.25 * atr:
                last_pullback_at = bar.timestamp
                if not in_material_pullback:
                    material_pullback_count += 1
                    in_material_pullback = True
            elif depth < 0.10 * atr:
                in_material_pullback = False
        if previous is not None:
            higher_lows += bar.low > previous.low
            lower_highs += bar.high < previous.high
        previous = bar
        if bar.close > bar.open:
            consecutive += 1
            maximum_consecutive = max(maximum_consecutive, consecutive)
        else:
            consecutive = 0
    returns = {}
    for minutes in (5, 15, 30, 60):
        subset = ordered[-minutes:]
        returns[f"{minutes}m"] = round(_pct(subset[-1].close, subset[0].open), 6) if subset else None
    return {
        "returnFromPriorClosePct": round(_pct(ask, prior_close), 6),
        "returnFromPremarketOpenPct": round(_pct(ask, pm["open"]), 6),
        "distanceFromPremarketVwapPct": round(_pct(ask, pm["vwapApprox"]), 6),
        "distanceFromNearestStructuralSupportPct": round(_pct(ask, structural_stop), 6),
        "moveFromPriorCloseAtr": round((ask - prior_close) / atr, 6),
        "returnsPct": returns,
        "maximumConsecutiveDirectionalUpBars": maximum_consecutive,
        "maximumPullbackAtr": round(max(pullbacks, default=0.0) / atr, 6),
        "materialPullbackCountAtExploratoryQuarterAtr": material_pullback_count,
        "timeSinceMeaningfulPullbackMinutes": _minutes(last_pullback_at, ordered[-1].timestamp) if last_pullback_at else None,
        "higherLowTransitionCount": higher_lows,
        "lowerHighTransitionCount": lower_highs,
        "last15ToPremarketRangeRatio": round(
            aggregate_bars(ordered[-15:])["range"] / aggregate_bars(premarket)["range"], 6
        ),
        "openingRangeAtr": round(op["range"] / atr, 6),
        "priceProgressPerVolume": round((ask - pm["open"]) / pm["volume"], 12) if pm["volume"] else None,
        "executionRewardRiskToNearestDefensibleStop": _execution_rr(
            ask, structural_stop, float(target)
        ),
        "thresholdAuthority": "RAW_RESEARCH_COVARIATES_ONLY",
    }


def _market_context(
    *, minute_store_root: Path, session_date: str, cutoff: datetime, source_hashes: dict[str, str]
) -> dict[str, Any]:
    results = []
    for symbol in BENCHMARKS:
        path = minute_store_root / session_date / f"{symbol}.json"
        try:
            bars = load_research_bars(path, expected_symbol=symbol)
            _validate_session_bars(bars, expected_date=session_date)
            bars = [bar for bar in bars if bar.timestamp < cutoff]
            source_hashes[f"cutoffMinuteEvidence:{symbol}"] = _bars_fingerprint(bars)
            pm = _between(bars, time(4, 0), time(9, 30))
            op = _between(bars, time(9, 30), DECISION_CUTOFF)
            results.append(
                {
                    "symbol": symbol,
                    "status": "AVAILABLE" if pm and len(op) == 5 else "INSUFFICIENT",
                    "premarketReturnPct": round(_pct(pm[-1].close, pm[0].open), 6) if pm else None,
                    "openingReturnPct": round(_pct(op[-1].close, op[0].open), 6) if len(op) == 5 else None,
                    "source": CANONICAL_SOURCE,
                }
            )
        except (OSError, RuntimeError, ValueError) as exc:
            results.append({"symbol": symbol, "status": "UNAVAILABLE", "reason": _redacted_error(exc)})
    return {"benchmarks": results, "authority": "RESEARCH_COVARIATE_ONLY"}


def _market_direction_agreement(context: Mapping[str, Any]) -> str:
    available = [
        item
        for item in context.get("benchmarks", [])
        if item.get("status") == "AVAILABLE" and item.get("openingReturnPct") is not None
    ]
    if not available:
        return "UNAVAILABLE"
    positive = sum(float(item["openingReturnPct"]) > 0 for item in available)
    if positive == len(available):
        return "LONG_AGREES_WITH_BROAD_MARKET"
    if positive == 0:
        return "LONG_OPPOSES_BROAD_MARKET"
    return "MIXED_BROAD_MARKET_CONTEXT"


def _data_basis(path: Path, bars: Sequence[ResearchBar]) -> dict[str, Any]:
    payload = _read_json(path)
    basis = payload.get("adjustmentBasis") or payload.get("priceBasis") or "UNSPECIFIED"
    suspicious = any(
        abs(_pct(current.open, previous.close)) >= 40.0
        for previous, current in zip(bars, bars[1:])
        if previous.close > 0
    )
    return {
        "priceDataBasis": basis,
        "dataBasisStatus": "DATA_BASIS_UNCERTAIN" if suspicious else "BASIS_RECORDED_OR_NO_DISCONTINUITY_FLAG",
        "patternClaimEligible": not suspicious,
    }


def _capture_identity(report: Mapping[str, Any], capture: Mapping[str, Any]) -> dict[str, Any]:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), Mapping) else {}
    return {
        "sourceCaptureTime": metadata.get("source_capture_time"),
        "sourceProvider": metadata.get("source_provider"),
        "captureStatus": capture.get("status") or "PRESERVED",
        "candidateCount": len(_candidate_rows(report)),
        "preservedMarketRegime": _preserved_market_regime(capture),
    }


def _preserved_market_regime(capture: Mapping[str, Any]) -> Any:
    value = capture.get("market_regime") or capture.get("marketRegime")
    if value is not None:
        return value
    metadata = capture.get("metadata")
    if isinstance(metadata, Mapping):
        return metadata.get("market_regime") or metadata.get("marketRegime")
    return None


def _candidate_rows(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = report.get("candidates")
    if not isinstance(rows, list):
        raise SuccessorSetupResearchError("TradePlan report has no candidate list.")
    normalized = [row for row in rows if isinstance(row, Mapping)]
    normalized.sort(key=lambda row: (int(row["rank"]), str(row.get("symbol") or "")))
    identities = [(int(row["rank"]), str(row.get("symbol") or "").upper()) for row in normalized]
    if len(identities) != len(set(identities)):
        raise SuccessorSetupResearchError("Candidate denominator contains duplicate rank/symbol identity.")
    return normalized


def _report_session_date(report: Mapping[str, Any]) -> str:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), Mapping) else {}
    raw = metadata.get("source_capture_time") or metadata.get("sourceCaptureTime")
    if not raw:
        raise SuccessorSetupResearchError("Report source capture time is unavailable.")
    return _parse_datetime(str(raw)).astimezone(EASTERN).date().isoformat()


def _validated_charter(path: Path) -> dict[str, Any]:
    charter = _read_json(path)
    if charter.get("sampleId") != SAMPLE_ID:
        raise SuccessorSetupResearchError("Wrong SETUP-002 sample charter.")
    if charter.get("policyFingerprint") != POLICY_FINGERPRINT:
        raise SuccessorSetupResearchError("Charter policy differs from the frozen rules.")
    if charter.get("charterFingerprint") != packet_fingerprint(charter):
        raise SuccessorSetupResearchError("Charter fingerprint is invalid.")
    return charter


def _validate_decision(decision: Mapping[str, Any]) -> None:
    if decision.get("sampleId") != SAMPLE_ID or decision.get("policyFingerprint") != POLICY_FINGERPRINT:
        raise SuccessorSetupResearchError("Pass 1 sample/policy identity is invalid.")
    if decision.get("outcomeEvidenceInspected") is not False:
        raise SuccessorSetupResearchError("Pass 1 is not outcome-blind.")
    if decision.get("decisionFingerprint") != packet_fingerprint(decision):
        raise SuccessorSetupResearchError("Pass 1 fingerprint is invalid.")
    for candidate in decision.get("candidates", []):
        expected = candidate.get("candidateFingerprint")
        if expected:
            copy = dict(candidate)
            copy.pop("candidateFingerprint", None)
            if expected != fingerprint_payload(copy):
                raise SuccessorSetupResearchError("Frozen candidate fingerprint is invalid.")


def _validate_session_bars(bars: Sequence[ResearchBar], *, expected_date: str) -> None:
    if any(bar.timestamp.astimezone(EASTERN).date().isoformat() != expected_date for bar in bars):
        raise SuccessorSetupResearchError("Candle belongs to the wrong Eastern session date.")


def _bars_fingerprint(bars: Sequence[ResearchBar]) -> str:
    return fingerprint_payload(
        [
            {
                "identity": bar.identity,
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": bar.source,
                "state": bar.state,
            }
            for bar in sorted(bars, key=lambda item: item.timestamp)
        ]
    )


def _research_opinion(decision: str, reason: str, setup_id: Any) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "setupId": setup_id,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "cannotInfluenceProduction": True,
    }


def _empty_counts() -> dict[str, int]:
    return {
        "tradingSessionsObserved": 0,
        "openingCandidatesObserved": 0,
        "candidatesFullyEvaluated": 0,
        "originalSetupsMissed": 0,
        "successorSetupsProposed": 0,
        "successorSetupsTriggered": 0,
        "untriggeredProposals": 0,
        "targetFirst": 0,
        "stopFirst": 0,
        "timeout": 0,
        "invalidatedProposals": 0,
        "ambiguous": 0,
        "noNewStructureObservations": 0,
        "evidenceFailures": 0,
    }


def _between(bars: Sequence[ResearchBar], start: time, end: time) -> list[ResearchBar]:
    return [bar for bar in bars if start <= bar.timestamp.astimezone(EASTERN).time() < end]


def _has_forced_flat_horizon(bars: Sequence[ResearchBar]) -> bool:
    return any(bar.timestamp.astimezone(EASTERN).time() == FORCED_FLAT for bar in bars)


def _execution_rr(entry: float, stop: float, target: float) -> float:
    risk = entry - stop
    return round((target - entry) / risk, 6) if risk > 0 else -1.0


def _pct(value: float, baseline: float) -> float:
    return round(((float(value) / float(baseline)) - 1.0) * 100.0, 6)


def _minutes(start: datetime | None, end: datetime) -> float | None:
    return round((end - start).total_seconds() / 60.0, 3) if start else None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SuccessorSetupResearchError(f"Naive timestamp is not allowed: {value}")
    return parsed


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise SuccessorSetupResearchError("Required evidence path is unavailable.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuccessorSetupResearchError(f"Cannot read JSON evidence: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SuccessorSetupResearchError(f"JSON evidence is not an object: {path.name}")
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _redacted_error(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error).replace(str(Path.home()), '<USER_HOME>')}"


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise SuccessorSetupResearchError(f"Conflicting write-once output exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    charter = commands.add_parser("charter")
    charter.add_argument("--created-at", required=True)
    charter.add_argument("--output", type=Path, required=True)
    pass1 = commands.add_parser("pass1")
    pass1.add_argument("--charter", type=Path, required=True)
    pass1.add_argument("--trade-plan", type=Path, required=True)
    pass1.add_argument("--capture", type=Path, required=True)
    pass1.add_argument("--minute-store", type=Path, required=True)
    pass1.add_argument("--observed-at", required=True)
    pass1.add_argument("--paper-result", type=Path)
    pass1.add_argument("--output", type=Path, required=True)
    pass2 = commands.add_parser("pass2")
    pass2.add_argument("--decision", type=Path, required=True)
    pass2.add_argument("--minute-store", type=Path, required=True)
    pass2.add_argument("--finalized-at", required=True)
    pass2.add_argument("--output", type=Path, required=True)
    dormant = commands.add_parser("dormant-plan")
    dormant.add_argument("--created-at", required=True)
    dormant.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "charter":
        result = create_sample_charter(created_at=args.created_at, output_path=args.output)
        summary = {"status": result["status"], "fingerprint": result["charterFingerprint"]}
    elif args.command == "pass1":
        result = build_pass_one(
            charter_path=args.charter,
            trade_plan_path=args.trade_plan,
            capture_path=args.capture,
            minute_store_root=args.minute_store,
            observed_at=args.observed_at,
            paper_result_path=args.paper_result,
            output_path=args.output,
        )
        summary = {"status": "FROZEN", "fingerprint": result["decisionFingerprint"]}
    elif args.command == "pass2":
        result = build_pass_two(
            decision_path=args.decision,
            minute_store_root=args.minute_store,
            finalized_at=args.finalized_at,
            output_path=args.output,
        )
        summary = {"status": "TERMINAL", "fingerprint": result["outcomeFingerprint"]}
    else:
        result = build_dormant_activation_plan(created_at=args.created_at, output_path=args.output)
        summary = {"status": result["status"], "fingerprint": result["activationPlanFingerprint"]}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
