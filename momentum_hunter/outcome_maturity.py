from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.outcome_explorer import OutcomeCandidate, build_outcome_explorer_report, percent
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURES_DIR
from momentum_hunter.study import StudyFilter


OUTCOME_MATURITY_LABEL = "OUTCOME MATURITY / DATA READINESS - MONITOR ONLY"
PENDING_WARNING_PCT = 30.0
GATE_LOCKED = "LOCKED"
GATE_DIAGNOSTIC = "DIAGNOSTIC"
GATE_READY = "READY"


@dataclass(frozen=True)
class ReadinessThresholds:
    outcome_explorer_next_day: int = 20
    opportunity_research_five_day: int = 50
    opportunity_score_design_five_day: int = 100
    weight_optimization_five_day: int = 300


@dataclass(frozen=True)
class ReadinessGate:
    name: str
    status: str
    current_count: int
    required_count: int
    reason: str
    estimated_earliest_readiness_date: str


@dataclass(frozen=True)
class OutcomeMaturityReport:
    label: str
    source: str
    filters: StudyFilter
    total_candidates: int
    study_eligible_candidates: int
    completed_next_day_outcomes: int
    completed_five_day_outcomes: int
    pending_next_day_outcomes: int
    pending_five_day_outcomes: int
    completed_outcome_pct: float
    pending_outcome_pct: float
    earliest_capture_date: str
    latest_capture_date: str
    earliest_date_with_usable_five_day_outcomes: str
    latest_date_with_pending_five_day_outcomes: str
    gates: list[ReadinessGate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_outcome_maturity_report(
    *,
    study_filter: StudyFilter | None = None,
    thresholds: ReadinessThresholds | None = None,
    captures_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
) -> OutcomeMaturityReport:
    study_filter = study_filter or StudyFilter()
    thresholds = thresholds or ReadinessThresholds()
    outcome_report = build_outcome_explorer_report(
        study_filter=study_filter,
        outcomes_csv=outcomes_csv,
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
    )
    candidates = outcome_report.candidates
    dates = sorted({candidate.capture_date for candidate in candidates if candidate.capture_date})
    completed_next_day = [candidate for candidate in candidates if candidate.next_day_return_pct is not None]
    completed_five_day = [candidate for candidate in candidates if candidate.five_day_return_pct is not None]
    pending_next_day = [candidate for candidate in candidates if candidate.next_day_return_pct is None]
    pending_five_day = [candidate for candidate in candidates if candidate.five_day_return_pct is None]

    earliest_five_day_dates = sorted({candidate.capture_date for candidate in completed_five_day if candidate.capture_date})
    pending_five_day_dates = sorted({candidate.capture_date for candidate in pending_five_day if candidate.capture_date})
    span = date_span(dates)
    latest_capture = dates[-1] if dates else ""

    gates = [
        build_gate(
            name="Outcome Explorer",
            current_count=len(completed_next_day),
            required_count=thresholds.outcome_explorer_next_day,
            outcome_label="completed next-day outcomes",
            latest_capture_date=latest_capture,
            date_span_days=span,
        ),
        build_gate(
            name="Opportunity Research",
            current_count=len(completed_five_day),
            required_count=thresholds.opportunity_research_five_day,
            outcome_label="completed five-day outcomes",
            latest_capture_date=latest_capture,
            date_span_days=span,
        ),
        build_gate(
            name="Opportunity Score design",
            current_count=len(completed_five_day),
            required_count=thresholds.opportunity_score_design_five_day,
            outcome_label="completed five-day outcomes",
            latest_capture_date=latest_capture,
            date_span_days=span,
        ),
        build_gate(
            name="Weight optimization",
            current_count=len(completed_five_day),
            required_count=thresholds.weight_optimization_five_day,
            outcome_label="completed five-day outcomes",
            latest_capture_date=latest_capture,
            date_span_days=span,
        ),
    ]
    warnings = readiness_warnings(
        total_candidates=len(candidates),
        completed_five_day_count=len(completed_five_day),
        pending_five_day_count=len(pending_five_day),
        gates=gates,
    )
    if not captures_csv.exists():
        warnings.append("analysis-captures.csv not found")
    if not outcomes_csv.exists():
        warnings.append("analysis-outcomes.csv not found")

    return OutcomeMaturityReport(
        label=OUTCOME_MATURITY_LABEL,
        source="analysis-captures.csv + analysis-outcomes.csv + active raw capture identity + review-decisions.json context",
        filters=study_filter,
        total_candidates=len(candidates),
        study_eligible_candidates=sum(1 for candidate in candidates if candidate.is_study_eligible),
        completed_next_day_outcomes=len(completed_next_day),
        completed_five_day_outcomes=len(completed_five_day),
        pending_next_day_outcomes=len(pending_next_day),
        pending_five_day_outcomes=len(pending_five_day),
        completed_outcome_pct=percent(len(completed_five_day), len(candidates)),
        pending_outcome_pct=percent(len(pending_five_day), len(candidates)),
        earliest_capture_date=dates[0] if dates else "n/a",
        latest_capture_date=latest_capture or "n/a",
        earliest_date_with_usable_five_day_outcomes=earliest_five_day_dates[0] if earliest_five_day_dates else "n/a",
        latest_date_with_pending_five_day_outcomes=pending_five_day_dates[-1] if pending_five_day_dates else "n/a",
        gates=gates,
        warnings=unique_preserve_order(warnings),
    )


def build_gate(
    *,
    name: str,
    current_count: int,
    required_count: int,
    outcome_label: str,
    latest_capture_date: str,
    date_span_days: int,
) -> ReadinessGate:
    if current_count >= required_count:
        return ReadinessGate(
            name=name,
            status=GATE_READY,
            current_count=current_count,
            required_count=required_count,
            reason=f"{current_count} {outcome_label} / minimum {required_count} required",
            estimated_earliest_readiness_date="ready now",
        )
    status = GATE_LOCKED if current_count == 0 else GATE_DIAGNOSTIC
    return ReadinessGate(
        name=name,
        status=status,
        current_count=current_count,
        required_count=required_count,
        reason=f"{current_count} {outcome_label} / minimum {required_count} required",
        estimated_earliest_readiness_date=estimate_readiness_date(
            current_count=current_count,
            required_count=required_count,
            latest_capture_date=latest_capture_date,
            date_span_days=date_span_days,
        ),
    )


def estimate_readiness_date(
    *,
    current_count: int,
    required_count: int,
    latest_capture_date: str,
    date_span_days: int,
) -> str:
    if current_count >= required_count:
        return "ready now"
    if not latest_capture_date:
        return "unknown - no captures"
    if current_count <= 0:
        return "unknown - no completed outcomes yet"
    latest = parse_date(latest_capture_date)
    if latest is None:
        return "unknown - invalid latest capture date"
    rate_per_day = current_count / max(1, date_span_days)
    if rate_per_day <= 0:
        return "unknown - insufficient completion rate"
    days_needed = int((required_count - current_count + rate_per_day - 1) // rate_per_day)
    return (latest + timedelta(days=max(1, days_needed))).isoformat()


def readiness_warnings(
    *,
    total_candidates: int,
    completed_five_day_count: int,
    pending_five_day_count: int,
    gates: list[ReadinessGate],
) -> list[str]:
    warnings = ["DO NOT USE FOR TRADING DECISIONS"]
    if any(gate.status != GATE_READY for gate in gates):
        warnings.append("INSUFFICIENT COMPLETED OUTCOMES")
    if completed_five_day_count < 10:
        warnings.append("DIAGNOSTIC ONLY")
    if total_candidates and percent(pending_five_day_count, total_candidates) >= PENDING_WARNING_PCT:
        warnings.append("HIGH PENDING RATE")
    return warnings


def date_span(values: list[str]) -> int:
    parsed = [item for item in (parse_date(value) for value in values) if item is not None]
    if not parsed:
        return 0
    return (max(parsed) - min(parsed)).days + 1


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
