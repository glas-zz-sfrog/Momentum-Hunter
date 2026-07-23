from __future__ import annotations

import copy
import json
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR


RESEARCH_MATURITY_SCHEMA_VERSION = 1
MATURITY_ENGINE_VERSION = "evidence_analytics_maturity_v1"
CENSUS_ENGINE_VERSION = "sqlite_evidence_census_v1"
DEFAULT_STALE_AFTER = timedelta(hours=24)
MAX_GATE_ROWS = 20
MAX_TABLE_ROWS = 50
MAX_QUESTION_ROWS = 20
MAX_WARNINGS = 40


@dataclass(frozen=True)
class ResearchMaturityPaths:
    maturity_path: Path
    census_path: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path = DATA_DIR) -> ResearchMaturityPaths:
        reports_dir = data_dir / "reports"
        return cls(
            maturity_path=reports_dir / "evidence-analytics-maturity-latest.json",
            census_path=reports_dir / "evidence-census-latest.json",
        )


class WorkstationResearchMaturityService:
    """Projects persisted research-maturity reports without recalculating them."""

    def __init__(
        self,
        paths: ResearchMaturityPaths | None = None,
        *,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> None:
        if stale_after.total_seconds() <= 0:
            raise ValueError("Research maturity stale threshold must be positive.")
        self.paths = paths or ResearchMaturityPaths.from_data_dir()
        self.stale_after = stale_after
        self._lock = threading.RLock()
        self._signature: tuple[object, object] | None = None
        self._maturity_payload: dict[str, Any] | None = None
        self._census_payload: dict[str, Any] | None = None
        self._maturity_error = ""
        self._census_error = ""

    def snapshot(self, *, observed_at: datetime | None = None) -> dict[str, Any]:
        observed_at = as_utc(observed_at or datetime.now(timezone.utc))
        signature = (
            path_signature(self.paths.maturity_path),
            path_signature(self.paths.census_path),
        )
        with self._lock:
            if signature != self._signature:
                self._reload(signature)
            snapshot = build_research_maturity_snapshot(
                maturity_payload=self._maturity_payload,
                census_payload=self._census_payload,
                maturity_error=self._maturity_error,
                census_error=self._census_error,
                paths=self.paths,
                observed_at=observed_at,
                stale_after=self.stale_after,
            )
        return copy.deepcopy(snapshot)

    def _reload(self, signature: tuple[object, object]) -> None:
        self._maturity_payload, self._maturity_error = load_report(
            self.paths.maturity_path,
            expected_engine=MATURITY_ENGINE_VERSION,
        )
        self._census_payload, self._census_error = load_report(
            self.paths.census_path,
            expected_engine=CENSUS_ENGINE_VERSION,
        )
        self._signature = signature


def build_research_maturity_snapshot(
    *,
    maturity_payload: dict[str, Any] | None,
    census_payload: dict[str, Any] | None,
    maturity_error: str = "",
    census_error: str = "",
    paths: ResearchMaturityPaths | None = None,
    observed_at: datetime,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> dict[str, Any]:
    paths = paths or ResearchMaturityPaths.from_data_dir()
    observed_at = as_utc(observed_at)
    if stale_after.total_seconds() <= 0:
        raise ValueError("Research maturity stale threshold must be positive.")
    if maturity_payload is None:
        return unavailable_snapshot(
            observed_at,
            paths,
            maturity_error or "The persisted research-maturity report is unavailable.",
        )

    try:
        maturity = project_maturity(maturity_payload)
    except ValueError as exc:
        return unavailable_snapshot(observed_at, paths, str(exc))

    warnings = unique_text(
        [
            *maturity["warnings"],
            census_error,
        ]
    )
    partial = False
    census = empty_census()
    census_valid = False
    if census_payload is None:
        partial = True
        warnings.append(
            census_error or "The persisted evidence census is unavailable."
        )
    else:
        try:
            census = project_census(census_payload)
            census_valid = True
            warnings.extend(census["warnings"])
        except ValueError as exc:
            partial = True
            warnings.append(str(exc))

    maturity_generated_at = parse_timestamp(maturity_payload.get("generated_at"))
    census_generated_at = (
        parse_timestamp(census_payload.get("generated_at"))
        if census_valid and census_payload is not None
        else None
    )
    if maturity_generated_at is None:
        partial = True
        warnings.append("The research-maturity report has no valid generated timestamp.")
    if census_valid and census_generated_at is None:
        partial = True
        warnings.append("The evidence census has no valid generated timestamp.")

    source_times = [
        value
        for value in (maturity_generated_at, census_generated_at)
        if value is not None
    ]
    source_as_of = min(source_times) if source_times else None
    stale_sources = [
        label
        for label, value in (
            (paths.maturity_path.name, maturity_generated_at),
            (paths.census_path.name, census_generated_at),
        )
        if value is not None and observed_at - value > stale_after
    ]
    if stale_sources:
        threshold_hours = stale_after.total_seconds() / 3600
        warnings.append(
            f"Persisted source is older than the {threshold_hours:g}-hour display threshold: "
            + ", ".join(stale_sources)
            + "."
        )

    no_evidence = (
        maturity["totalAlerts"] == 0
        and census["captures"] == 0
        and census["candidateRows"] == 0
        and census["minuteBars"] == 0
        and census["evidenceRuns"] == 0
    )
    state = (
        "PARTIAL"
        if partial
        else "EMPTY"
        if no_evidence
        else "STALE"
        if stale_sources
        else "AVAILABLE"
    )
    summary = (
        f"{state} | Persisted research maturity has {maturity['completedAlerts']} completed "
        f"alert(s) against {maturity['evidenceGate']['requiredAlerts']} required for the "
        f"current evidence gate; strategy-change recommendations remain prohibited. "
        f"The separate census contains {census['captures']} capture(s), "
        f"{census['candidateRows']} candidate row(s), and {census['minuteBars']} minute bar(s)."
    )
    return {
        "schemaVersion": RESEARCH_MATURITY_SCHEMA_VERSION,
        "state": state,
        "observedAt": timestamp_text(observed_at),
        "sourceAsOf": timestamp_text(source_as_of) if source_as_of else None,
        "maturityGeneratedAt": (
            timestamp_text(maturity_generated_at) if maturity_generated_at else None
        ),
        "censusGeneratedAt": (
            timestamp_text(census_generated_at) if census_generated_at else None
        ),
        "sourceLabel": f"{paths.maturity_path.name} + {paths.census_path.name}",
        "summary": (
            summary
            + " Research evidence only; no score, readiness gate, alert, plan, or execution "
            "behavior was changed."
        ),
        "maturityOverallStatus": maturity["overallStatus"],
        "censusOverallStatus": census["overallStatus"],
        "sampleConfidence": maturity["sampleConfidence"],
        "measurableEdgeStatus": maturity["measurableEdgeStatus"],
        "strategyOptimizationStatus": maturity["strategyOptimizationStatus"],
        "strategyChangeRecommendationsAllowed": False,
        "maturityTotalAlerts": maturity["totalAlerts"],
        "maturityCompletedAlerts": maturity["completedAlerts"],
        "maturityPendingAlerts": maturity["pendingAlerts"],
        "maturityUnscorableAlerts": maturity["unscorableAlerts"],
        "maturityCompletionRatePct": maturity["completionRatePct"],
        "evidenceNeededToNextGate": maturity["evidenceNeededToNextGate"],
        "evidenceGate": maturity["evidenceGate"],
        "gates": maturity["gates"],
        "gateCount": maturity["gateCount"],
        "displayedGateCount": len(maturity["gates"]),
        "questions": maturity["questions"],
        "questionCount": maturity["questionCount"],
        "displayedQuestionCount": len(maturity["questions"]),
        "censusTotalAlerts": census["totalAlerts"],
        "censusCompletedAlerts": census["completedAlerts"],
        "censusPendingAlerts": census["pendingAlerts"],
        "censusUnscorableAlerts": census["unscorableAlerts"],
        "censusCompletionRatePct": census["completionRatePct"],
        "captures": census["captures"],
        "candidateRows": census["candidateRows"],
        "studyEligibleCaptures": census["studyEligibleCaptures"],
        "quarantinedCaptures": census["quarantinedCaptures"],
        "minuteBars": census["minuteBars"],
        "minuteBarSymbols": census["minuteBarSymbols"],
        "evidenceRuns": census["evidenceRuns"],
        "evidenceMetrics": census["evidenceMetrics"],
        "candidateReviews": census["candidateReviews"],
        "watchlistItems": census["watchlistItems"],
        "entryPlans": census["entryPlans"],
        "completeEntryPlans": census["completeEntryPlans"],
        "incompleteEntryPlans": census["incompleteEntryPlans"],
        "tableCounts": census["tableCounts"],
        "tableCount": census["tableCount"],
        "displayedTableCount": len(census["tableCounts"]),
        "warnings": unique_text(warnings)[:MAX_WARNINGS],
        "safetyNotes": maturity["safetyNotes"][:MAX_WARNINGS],
        "researchOnly": True,
        "readOnly": True,
    }


def project_maturity(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("strategy_change_recommendations_allowed") is not False:
        raise ValueError(
            "The persisted research-maturity report does not preserve the strategy-change lock."
        )
    raw_gate = required_object(payload, "evidence_gate", "research-maturity")
    gates = required_object_rows(payload, "overall_gates", "research-maturity")
    projected_gates = []
    for index, gate in enumerate(gates):
        if gate.get("strategy_change_allowed") is not False:
            raise ValueError(
                f"Research-maturity gate {index + 1} does not preserve the strategy-change lock."
            )
        projected_gates.append(
            {
                "name": required_text(gate, "name", f"gate {index + 1}"),
                "status": required_text(gate, "status", f"gate {index + 1}"),
                "currentCompletedAlerts": required_nonnegative_int(
                    gate, "current_completed_alerts", f"gate {index + 1}"
                ),
                "requiredCompletedAlerts": required_nonnegative_int(
                    gate, "required_completed_alerts", f"gate {index + 1}"
                ),
                "completedNeeded": required_nonnegative_int(
                    gate, "completed_needed", f"gate {index + 1}"
                ),
                "allowedAction": required_text(
                    gate, "allowed_action", f"gate {index + 1}"
                ),
                "strategyChangeAllowed": False,
            }
        )
    if len({row["name"] for row in projected_gates}) != len(projected_gates):
        raise ValueError("The persisted research-maturity gates contain duplicate names.")

    can_answer = required_object(payload, "can_answer", "research-maturity")
    questions = [
        {
            "question": question_label(key),
            "answer": text_value(value) or "Unavailable",
        }
        for key, value in list(can_answer.items())[:MAX_QUESTION_ROWS]
        if text_value(key)
    ]
    warnings = required_text_list(payload, "warnings", "research-maturity")
    safety_notes = required_text_list(payload, "safety_notes", "research-maturity")
    gate = {
        "completedAlerts": required_nonnegative_int(
            raw_gate, "completed_alerts", "evidence gate"
        ),
        "requiredAlerts": required_nonnegative_int(
            raw_gate, "required_alerts", "evidence gate"
        ),
        "evidenceStatus": required_text(
            raw_gate, "evidence_status", "evidence gate"
        ),
        "allowedAction": required_text(raw_gate, "allowed_action", "evidence gate"),
        "strategyOptimizationStatus": required_text(
            raw_gate, "strategy_optimization_status", "evidence gate"
        ),
        "reason": required_text(raw_gate, "reason", "evidence gate"),
    }
    projected = {
        "overallStatus": required_text(payload, "overall_status", "research-maturity"),
        "totalAlerts": required_nonnegative_int(
            payload, "total_alerts", "research-maturity"
        ),
        "completedAlerts": required_nonnegative_int(
            payload, "completed_alerts", "research-maturity"
        ),
        "pendingAlerts": required_nonnegative_int(
            payload, "pending_alerts", "research-maturity"
        ),
        "unscorableAlerts": required_nonnegative_int(
            payload, "unscorable_alerts", "research-maturity"
        ),
        "completionRatePct": optional_number(
            payload, "completion_rate_pct", "research-maturity"
        ),
        "measurableEdgeStatus": required_text(
            payload, "measurable_edge_status", "research-maturity"
        ),
        "sampleConfidence": required_text(
            payload, "sample_confidence", "research-maturity"
        ),
        "strategyOptimizationStatus": required_text(
            payload, "strategy_optimization_status", "research-maturity"
        ),
        "evidenceNeededToNextGate": required_nonnegative_int(
            payload, "evidence_needed_to_next_gate", "research-maturity"
        ),
        "evidenceGate": gate,
        "gates": projected_gates[:MAX_GATE_ROWS],
        "gateCount": len(gates),
        "questions": questions,
        "questionCount": len(can_answer),
        "warnings": warnings
        + (
            [
                f"Showing {MAX_GATE_ROWS} of {len(gates)} persisted maturity gates."
            ]
            if len(gates) > MAX_GATE_ROWS
            else []
        )
        + (
            [
                f"Showing {MAX_QUESTION_ROWS} of {len(can_answer)} persisted research questions."
            ]
            if len(can_answer) > MAX_QUESTION_ROWS
            else []
        ),
        "safetyNotes": safety_notes,
    }
    if (
        projected["completedAlerts"]
        + projected["pendingAlerts"]
        + projected["unscorableAlerts"]
        != projected["totalAlerts"]
    ):
        raise ValueError(
            "The persisted research-maturity alert counts do not reconcile."
        )
    if gate["completedAlerts"] != projected["completedAlerts"]:
        raise ValueError(
            "The persisted evidence gate does not match the completed-alert count."
        )
    if gate["strategyOptimizationStatus"] != projected["strategyOptimizationStatus"]:
        raise ValueError(
            "The persisted evidence gate does not match the strategy-optimization lock."
        )
    if projected["strategyOptimizationStatus"] != "LOCKED":
        raise ValueError(
            "The persisted research-maturity report does not keep strategy optimization locked."
        )
    if gate["strategyOptimizationStatus"] != "LOCKED":
        raise ValueError(
            "The persisted evidence gate does not keep strategy optimization locked."
        )
    expected_gate_gap = max(0, gate["requiredAlerts"] - gate["completedAlerts"])
    if projected["evidenceNeededToNextGate"] != expected_gate_gap:
        raise ValueError(
            "The persisted evidence-needed count does not match the current evidence gate."
        )
    for item in projected_gates:
        if item["currentCompletedAlerts"] != projected["completedAlerts"]:
            raise ValueError(
                f"Research-maturity gate '{item['name']}' does not match the completed-alert count."
            )
        expected_needed = max(
            0,
            item["requiredCompletedAlerts"] - item["currentCompletedAlerts"],
        )
        if item["completedNeeded"] != expected_needed:
            raise ValueError(
                f"Research-maturity gate '{item['name']}' has an inconsistent evidence gap."
            )
    return projected


def project_census(payload: dict[str, Any]) -> dict[str, Any]:
    table_counts = required_object(payload, "table_counts", "evidence census")
    all_table_rows = [
        {"name": text_value(name), "count": nonnegative_int_value(value, f"table '{name}'")}
        for name, value in table_counts.items()
        if text_value(name)
    ]
    if len(all_table_rows) != len(table_counts):
        raise ValueError("The persisted evidence census has an empty table name.")
    if len({row["name"].lower() for row in all_table_rows}) != len(all_table_rows):
        raise ValueError("The persisted evidence census has duplicate table names.")
    table_rows = all_table_rows[:MAX_TABLE_ROWS]
    alerts = required_object(payload, "alerts", "evidence census")
    captures = required_object(payload, "captures", "evidence census")
    minute_bars = required_object(payload, "minute_bars", "evidence census")
    evidence_runs = required_object(payload, "evidence_runs", "evidence census")
    user_state = required_object(payload, "user_state", "evidence census")
    warnings = required_text_list(payload, "warnings", "evidence census")
    if len(table_counts) > MAX_TABLE_ROWS:
        warnings.append(
            f"Showing {MAX_TABLE_ROWS} of {len(table_counts)} persisted table counts."
        )
    projected = {
        "overallStatus": required_text(payload, "overall_status", "evidence census"),
        "totalAlerts": required_nonnegative_int(alerts, "total_alerts", "census alerts"),
        "completedAlerts": required_nonnegative_int(alerts, "completed", "census alerts"),
        "pendingAlerts": required_nonnegative_int(alerts, "pending", "census alerts"),
        "unscorableAlerts": required_nonnegative_int(
            alerts, "unscorable", "census alerts"
        ),
        "completionRatePct": optional_number(
            alerts, "completion_rate_pct", "census alerts"
        ),
        "captures": required_nonnegative_int(
            captures, "total_captures", "census captures"
        ),
        "candidateRows": required_nonnegative_int(
            captures, "total_candidates", "census captures"
        ),
        "studyEligibleCaptures": required_nonnegative_int(
            captures, "study_eligible", "census captures"
        ),
        "quarantinedCaptures": required_nonnegative_int(
            captures, "quarantined", "census captures"
        ),
        "minuteBars": required_nonnegative_int(
            minute_bars, "total_bars", "census minute bars"
        ),
        "minuteBarSymbols": required_nonnegative_int(
            minute_bars, "symbols", "census minute bars"
        ),
        "evidenceRuns": required_nonnegative_int(
            evidence_runs, "runs", "census evidence runs"
        ),
        "evidenceMetrics": required_nonnegative_int(
            evidence_runs, "metrics", "census evidence runs"
        ),
        "candidateReviews": required_nonnegative_int(
            user_state, "candidate_reviews", "census user state"
        ),
        "watchlistItems": required_nonnegative_int(
            user_state, "watchlist_items", "census user state"
        ),
        "entryPlans": required_nonnegative_int(
            user_state, "entry_plans", "census user state"
        ),
        "completeEntryPlans": required_nonnegative_int(
            user_state, "complete_entry_plans", "census user state"
        ),
        "incompleteEntryPlans": required_nonnegative_int(
            user_state, "incomplete_entry_plans", "census user state"
        ),
        "tableCounts": table_rows,
        "tableCount": len(table_counts),
        "warnings": warnings,
    }
    if (
        projected["completedAlerts"]
        + projected["pendingAlerts"]
        + projected["unscorableAlerts"]
        != projected["totalAlerts"]
    ):
        raise ValueError("The persisted evidence-census alert counts do not reconcile.")
    if projected["completeEntryPlans"] + projected["incompleteEntryPlans"] > projected["entryPlans"]:
        raise ValueError("The persisted evidence-census plan counts do not reconcile.")
    return projected


def empty_census() -> dict[str, Any]:
    return {
        "overallStatus": "UNAVAILABLE",
        "totalAlerts": 0,
        "completedAlerts": 0,
        "pendingAlerts": 0,
        "unscorableAlerts": 0,
        "completionRatePct": None,
        "captures": 0,
        "candidateRows": 0,
        "studyEligibleCaptures": 0,
        "quarantinedCaptures": 0,
        "minuteBars": 0,
        "minuteBarSymbols": 0,
        "evidenceRuns": 0,
        "evidenceMetrics": 0,
        "candidateReviews": 0,
        "watchlistItems": 0,
        "entryPlans": 0,
        "completeEntryPlans": 0,
        "incompleteEntryPlans": 0,
        "tableCounts": [],
        "tableCount": 0,
        "warnings": [],
    }


def unavailable_snapshot(
    observed_at: datetime,
    paths: ResearchMaturityPaths,
    reason: str,
) -> dict[str, Any]:
    census = empty_census()
    return {
        "schemaVersion": RESEARCH_MATURITY_SCHEMA_VERSION,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "sourceAsOf": None,
        "maturityGeneratedAt": None,
        "censusGeneratedAt": None,
        "sourceLabel": f"{paths.maturity_path.name} + {paths.census_path.name}",
        "summary": (
            f"UNAVAILABLE | {reason} No research, scoring, readiness, alert, planning, "
            "or execution conclusion was inferred."
        ),
        "maturityOverallStatus": "UNAVAILABLE",
        "censusOverallStatus": "UNAVAILABLE",
        "sampleConfidence": "UNAVAILABLE",
        "measurableEdgeStatus": "UNAVAILABLE",
        "strategyOptimizationStatus": "LOCKED",
        "strategyChangeRecommendationsAllowed": False,
        "maturityTotalAlerts": 0,
        "maturityCompletedAlerts": 0,
        "maturityPendingAlerts": 0,
        "maturityUnscorableAlerts": 0,
        "maturityCompletionRatePct": None,
        "evidenceNeededToNextGate": 0,
        "evidenceGate": {
            "completedAlerts": 0,
            "requiredAlerts": 0,
            "evidenceStatus": "UNAVAILABLE",
            "allowedAction": "No action available",
            "strategyOptimizationStatus": "LOCKED",
            "reason": reason,
        },
        "gates": [],
        "gateCount": 0,
        "displayedGateCount": 0,
        "questions": [],
        "questionCount": 0,
        "displayedQuestionCount": 0,
        "censusTotalAlerts": census["totalAlerts"],
        "censusCompletedAlerts": census["completedAlerts"],
        "censusPendingAlerts": census["pendingAlerts"],
        "censusUnscorableAlerts": census["unscorableAlerts"],
        "censusCompletionRatePct": census["completionRatePct"],
        "captures": census["captures"],
        "candidateRows": census["candidateRows"],
        "studyEligibleCaptures": census["studyEligibleCaptures"],
        "quarantinedCaptures": census["quarantinedCaptures"],
        "minuteBars": census["minuteBars"],
        "minuteBarSymbols": census["minuteBarSymbols"],
        "evidenceRuns": census["evidenceRuns"],
        "evidenceMetrics": census["evidenceMetrics"],
        "candidateReviews": census["candidateReviews"],
        "watchlistItems": census["watchlistItems"],
        "entryPlans": census["entryPlans"],
        "completeEntryPlans": census["completeEntryPlans"],
        "incompleteEntryPlans": census["incompleteEntryPlans"],
        "tableCounts": [],
        "tableCount": 0,
        "displayedTableCount": 0,
        "warnings": [reason],
        "safetyNotes": [
            "Research evidence only; strategy changes remain prohibited."
        ],
        "researchOnly": True,
        "readOnly": True,
    }


def load_report(
    path: Path,
    *,
    expected_engine: str,
) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, f"{path.name} does not exist."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{path.name} is unreadable: {type(exc).__name__}."
    if not isinstance(payload, dict):
        return None, f"{path.name} must contain a JSON object."
    if payload.get("schema_version") != 1:
        return None, f"{path.name} has an unsupported schema version."
    if payload.get("engine_version") != expected_engine:
        return None, f"{path.name} has an unexpected engine version."
    return payload, ""


def path_signature(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return path.name, stat.st_mtime_ns, stat.st_size


def required_object(
    payload: dict[str, Any],
    name: str,
    label: str,
) -> dict[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"The persisted {label} report has invalid object '{name}'.")
    return value


def required_object_rows(
    payload: dict[str, Any],
    name: str,
    label: str,
) -> list[dict[str, Any]]:
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"The persisted {label} report has invalid rows '{name}'.")
    return value


def required_text(payload: dict[str, Any], name: str, label: str) -> str:
    value = text_value(payload.get(name))
    if not value:
        raise ValueError(f"The persisted {label} report is missing text '{name}'.")
    return value


def required_text_list(
    payload: dict[str, Any],
    name: str,
    label: str,
) -> list[str]:
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"The persisted {label} report has invalid text list '{name}'.")
    return unique_text(value)


def required_nonnegative_int(
    payload: dict[str, Any],
    name: str,
    label: str,
) -> int:
    return nonnegative_int_value(payload.get(name), f"{label}.{name}")


def nonnegative_int_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"The persisted research evidence has invalid count '{label}'.")
    return value


def optional_number(
    payload: dict[str, Any],
    name: str,
    label: str,
) -> float | None:
    value = payload.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"The persisted {label} report has invalid number '{name}'.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"The persisted {label} report has invalid number '{name}'.")
    return number


def parse_timestamp(value: object) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(parsed)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def question_label(value: object) -> str:
    return text_value(value).replace("_", " ").strip().title()


def text_value(value: object) -> str:
    return str(value or "").strip()


def unique_text(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = text_value(value)
        if text and text not in result:
            result.append(text)
    return result
