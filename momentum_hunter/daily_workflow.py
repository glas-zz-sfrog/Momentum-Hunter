from __future__ import annotations

from dataclasses import dataclass, field

from momentum_hunter.capture_health import CaptureHealthSnapshot
from momentum_hunter.entry_plans import EntryPlan, entry_plan_warnings
from momentum_hunter.models import Candidate
from momentum_hunter.outcome_maturity import OutcomeMaturityReport
from momentum_hunter.review import CandidateIdentity, ReviewStatus


@dataclass(frozen=True)
class ReviewStatusCounts:
    total_candidates: int = 0
    reviewed_candidates: int = 0
    unreviewed_candidates: int = 0
    interested_candidates: int = 0
    rejected_candidates: int = 0
    watchlist_candidates: int = 0


@dataclass(frozen=True)
class EntryPlanStatusCounts:
    watchlist_candidates: int = 0
    complete_plans: int = 0
    incomplete_plans: int = 0
    missing_trigger: int = 0
    missing_stop: int = 0
    missing_invalidation: int = 0
    missing_max_loss: int = 0
    watchlist_without_plan: int = 0


@dataclass(frozen=True)
class DailyWorkflowReport:
    review: ReviewStatusCounts
    entry_plans: EntryPlanStatusCounts
    completed_next_day_outcomes: int
    completed_five_day_outcomes: int
    pending_outcomes: int
    readiness_statuses: dict[str, str]
    capture_health_status: str
    warnings: list[str] = field(default_factory=list)
    workflow_score: int = 0


def build_daily_workflow_report(
    *,
    candidates: list[Candidate],
    identities: dict[str, CandidateIdentity],
    review_statuses: dict[str, ReviewStatus],
    entry_plans: dict[str, EntryPlan],
    capture_health: CaptureHealthSnapshot,
    outcome_maturity: OutcomeMaturityReport,
) -> DailyWorkflowReport:
    review = build_review_counts(candidates, identities, review_statuses)
    plan_counts = build_entry_plan_counts(candidates, identities, review_statuses, entry_plans)
    readiness_statuses = {gate.name: gate.status for gate in outcome_maturity.gates}
    warnings = build_workflow_warnings(
        review=review,
        entry_plans=plan_counts,
        capture_health=capture_health,
        readiness_statuses=readiness_statuses,
    )
    return DailyWorkflowReport(
        review=review,
        entry_plans=plan_counts,
        completed_next_day_outcomes=outcome_maturity.completed_next_day_outcomes,
        completed_five_day_outcomes=outcome_maturity.completed_five_day_outcomes,
        pending_outcomes=outcome_maturity.pending_five_day_outcomes,
        readiness_statuses=readiness_statuses,
        capture_health_status=capture_status(capture_health),
        warnings=warnings,
        workflow_score=workflow_score(
            review=review,
            entry_plans=plan_counts,
            capture_health=capture_health,
            warnings=warnings,
        ),
    )


def build_review_counts(
    candidates: list[Candidate],
    identities: dict[str, CandidateIdentity],
    review_statuses: dict[str, ReviewStatus],
) -> ReviewStatusCounts:
    counts = {status: 0 for status in ReviewStatus}
    for candidate in candidates:
        identity = identities.get(candidate.ticker)
        status = review_statuses.get(identity.key if identity else candidate.ticker, ReviewStatus.UNREVIEWED)
        counts[status] += 1
    total = len(candidates)
    reviewed = total - counts[ReviewStatus.UNREVIEWED]
    return ReviewStatusCounts(
        total_candidates=total,
        reviewed_candidates=reviewed,
        unreviewed_candidates=counts[ReviewStatus.UNREVIEWED],
        interested_candidates=counts[ReviewStatus.INTERESTED],
        rejected_candidates=counts[ReviewStatus.REJECTED],
        watchlist_candidates=counts[ReviewStatus.WATCHLIST],
    )


def build_entry_plan_counts(
    candidates: list[Candidate],
    identities: dict[str, CandidateIdentity],
    review_statuses: dict[str, ReviewStatus],
    entry_plans: dict[str, EntryPlan],
) -> EntryPlanStatusCounts:
    complete = 0
    incomplete = 0
    missing_trigger = 0
    missing_stop = 0
    missing_invalidation = 0
    missing_max_loss = 0
    no_plan = 0
    watchlist = 0
    for candidate in candidates:
        identity = identities.get(candidate.ticker)
        key = identity.key if identity else candidate.ticker
        if review_statuses.get(key, ReviewStatus.UNREVIEWED) != ReviewStatus.WATCHLIST:
            continue
        watchlist += 1
        plan = entry_plans.get(key)
        if plan is None:
            no_plan += 1
            incomplete += 1
            missing_trigger += 1
            missing_stop += 1
            missing_invalidation += 1
            missing_max_loss += 1
            continue
        warnings = entry_plan_warnings(plan)
        if plan.plan_complete and not warnings:
            complete += 1
        else:
            incomplete += 1
        missing_trigger += int("missing trigger" in warnings)
        missing_stop += int("missing stop" in warnings)
        missing_invalidation += int("missing invalidation" in warnings)
        missing_max_loss += int("missing max loss" in warnings)
    return EntryPlanStatusCounts(
        watchlist_candidates=watchlist,
        complete_plans=complete,
        incomplete_plans=incomplete,
        missing_trigger=missing_trigger,
        missing_stop=missing_stop,
        missing_invalidation=missing_invalidation,
        missing_max_loss=missing_max_loss,
        watchlist_without_plan=no_plan,
    )


def build_workflow_warnings(
    *,
    review: ReviewStatusCounts,
    entry_plans: EntryPlanStatusCounts,
    capture_health: CaptureHealthSnapshot,
    readiness_statuses: dict[str, str],
) -> list[str]:
    warnings = []
    if review.unreviewed_candidates:
        warnings.append("REVIEWS INCOMPLETE")
    if entry_plans.watchlist_without_plan:
        warnings.append("WATCHLIST HAS NO ENTRY PLAN")
    if entry_plans.incomplete_plans:
        warnings.append("INCOMPLETE ENTRY PLAN")
    if capture_health.last_failed_capture.failure_time:
        warnings.append("CAPTURE FAILURE DETECTED")
    if any(status == "LOCKED" for status in readiness_statuses.values()):
        warnings.append("READINESS GATE LOCKED")
    return warnings


def workflow_score(
    *,
    review: ReviewStatusCounts,
    entry_plans: EntryPlanStatusCounts,
    capture_health: CaptureHealthSnapshot,
    warnings: list[str],
) -> int:
    review_points = 40 if review.total_candidates == 0 else round(40 * review.reviewed_candidates / review.total_candidates)
    if entry_plans.watchlist_candidates == 0:
        plan_points = 30
    else:
        plan_points = round(30 * entry_plans.complete_plans / entry_plans.watchlist_candidates)
    capture_points = 0
    if capture_health.last_morning_capture.capture_time:
        capture_points += 10
    if capture_health.last_evening_capture.capture_time or capture_health.last_preopen_capture.capture_time:
        capture_points += 10
    warning_points = 10
    critical_warnings = {
        "REVIEWS INCOMPLETE",
        "WATCHLIST HAS NO ENTRY PLAN",
        "INCOMPLETE ENTRY PLAN",
        "CAPTURE FAILURE DETECTED",
    }
    warning_points -= min(10, 3 * sum(1 for warning in warnings if warning in critical_warnings))
    return max(0, min(100, review_points + plan_points + capture_points + warning_points))


def capture_status(capture_health: CaptureHealthSnapshot) -> str:
    if capture_health.last_failed_capture.failure_time:
        return "warning - last scheduled capture failed"
    if capture_health.last_morning_capture.capture_time and (
        capture_health.last_evening_capture.capture_time or capture_health.last_preopen_capture.capture_time
    ):
        return "healthy"
    return "incomplete"
