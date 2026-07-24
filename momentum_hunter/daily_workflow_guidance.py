from __future__ import annotations

from typing import Protocol

from momentum_hunter.daily_workflow import DailyWorkflowReport
from momentum_hunter.operator_review import OperatorReviewContext


class DailyWorkflowStyle(Protocol):
    is_warning: bool
    decision_status: str


def daily_workflow_trust_state(
    report: DailyWorkflowReport,
    style: DailyWorkflowStyle,
    context: OperatorReviewContext,
) -> dict[str, str]:
    if not context.can_review:
        return {
            "title": f"Trust blocker: {context.label}",
            "detail": context.block_reason or context.guidance or "This view is not available for daily review.",
            "level": "blocked",
        }
    if report.capture_health_status.startswith("warning"):
        return {
            "title": "Trust blocker: capture failure detected",
            "detail": "Open Capture Health before trusting today's workflow.",
            "level": "blocked",
        }
    if report.capture_health_status == "incomplete":
        return {
            "title": "Trust attention: capture health incomplete",
            "detail": "Capture status is incomplete. Review Capture Health before assuming the day is clear.",
            "level": "attention",
        }
    if style.is_warning:
        return {
            "title": f"Trust attention: {context.label}",
            "detail": context.guidance or style.decision_status,
            "level": "attention",
        }
    return {
        "title": f"Trust clear: {context.label}",
        "detail": "Current workflow facts are loaded. Continue with the highlighted next required action.",
        "level": "complete",
    }


def daily_workflow_next_action(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return {
            "title": "Next Required Action: restore a reviewable current workflow",
            "detail": context.block_reason or context.guidance or "Return to a current reviewable capture before daily review.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "blocked",
        }
    if report.capture_health_status.startswith("warning") or report.capture_health_status == "incomplete":
        return {
            "title": "Next Required Action: inspect Capture Health",
            "detail": "Capture health needs attention before the workflow lights can be trusted.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "blocked" if report.capture_health_status.startswith("warning") else "attention",
        }
    if report.review.total_candidates == 0:
        return {
            "title": "Next Required Action: load review candidates",
            "detail": "No candidates are available in the current workflow. Run or load a current capture before review.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "attention",
        }
    if report.review.unreviewed_candidates:
        return {
            "title": "Next Required Action: review candidates",
            "detail": f"{report.review.unreviewed_candidates} candidate(s) still need Interested, Rejected, or Watchlist decisions.",
            "action_key": "review",
            "active_step": "review",
            "level": "active",
        }
    if report.entry_plans.watchlist_candidates == 0:
        return {
            "title": "Daily workflow complete",
            "detail": "All candidates are reviewed and no Watchlist candidates are selected for a report.",
            "action_key": "",
            "active_step": "",
            "level": "complete",
        }
    if report.entry_plans.incomplete_plans:
        return {
            "title": "Next Required Action: complete watchlist plans",
            "detail": (
                f"{report.entry_plans.incomplete_plans} Watchlist plan(s) need trigger, stop, invalidation, "
                "or max-loss discipline."
            ),
            "action_key": "review",
            "active_step": "plans",
            "level": "active",
        }
    return {
        "title": "Next Required Action: generate the Watchlist Report",
        "detail": "Watchlist candidates have complete plan discipline. Generate the report, then use Readiness Gate as a check.",
        "action_key": "report",
        "active_step": "report",
        "level": "active",
    }


def daily_workflow_steps(
    report: DailyWorkflowReport,
    context: OperatorReviewContext,
    next_action: dict[str, str],
) -> list[dict[str, str]]:
    active_step = next_action["active_step"]
    readiness_locked = any(status == "LOCKED" for status in report.readiness_statuses.values())
    steps = [
        daily_workflow_capture_step(report, context),
        daily_workflow_review_step(report, context),
        daily_workflow_plan_step(report, context),
        daily_workflow_report_step(report, context),
        daily_workflow_readiness_step(readiness_locked),
    ]
    for step in steps:
        if step["id"] == active_step and step["level"] not in {"blocked", "locked"}:
            step["level"] = "active"
            step["light"] = "blue"
    return steps


def daily_workflow_capture_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "blocked",
            "Blocked",
            "red",
            "A current reviewable capture.",
            context.block_reason or context.guidance or "This view is not available for daily review.",
            "Open Capture Health for diagnostics; return to a current capture before continuing.",
            "capture",
        )
    if report.capture_health_status.startswith("warning"):
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "blocked",
            "Blocked",
            "red",
            "Successful scheduled or current capture health.",
            "A scheduled capture failure is recorded.",
            "Open Capture Health before trusting today's workflow.",
            "capture",
        )
    if report.capture_health_status == "healthy":
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "complete",
            "Complete",
            "green",
            "Capture status from existing Capture Health.",
            "None.",
            "Capture Health reports healthy for the current workflow.",
            "capture",
        )
    return daily_workflow_step(
        "capture",
        "Capture Health",
        "attention",
        "Needs capture",
        "yellow",
        "Morning plus evening or preopen capture health.",
        "Capture Health is incomplete.",
        "Open Capture Health or load a current reviewable capture.",
        "capture",
    )


def daily_workflow_review_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "review",
            "Morning Review",
            "A current reviewable capture.",
            context.block_reason or context.guidance or "This view is read-only.",
            "review",
        )
    if report.review.total_candidates == 0:
        return daily_workflow_waiting_step(
            "review",
            "Morning Review",
            "One or more loaded candidates.",
            "No review candidates are available in the current workflow.",
            "review",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_step(
            "review",
            "Morning Review",
            "attention",
            "Needs review",
            "yellow",
            "Loaded candidates and a reviewable context.",
            f"{report.review.unreviewed_candidates} candidate(s) still need a review decision.",
            "Mark each candidate Interested, Rejected, or Watchlist.",
            "review",
        )
    return daily_workflow_step(
        "review",
        "Morning Review",
        "complete",
        "Complete",
        "green",
        "All loaded candidates reviewed.",
        "None.",
        f"{report.review.reviewed_candidates} of {report.review.total_candidates} candidate(s) are reviewed.",
        "review",
    )


def daily_workflow_plan_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "plans",
            "Watchlist Plans",
            "A reviewable workflow.",
            context.block_reason or context.guidance or "This view is read-only.",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_waiting_step(
            "plans",
            "Watchlist Plans",
            "Morning Review complete.",
            "Review decisions are still incomplete.",
        )
    if report.entry_plans.watchlist_candidates == 0:
        return daily_workflow_step(
            "plans",
            "Watchlist Plans",
            "waiting",
            "No watchlist",
            "gray",
            "At least one candidate marked Watchlist.",
            "No Watchlist candidates are selected.",
            "No entry plan is needed unless a candidate is moved to Watchlist.",
            "",
        )
    if report.entry_plans.incomplete_plans:
        return daily_workflow_step(
            "plans",
            "Watchlist Plans",
            "attention",
            "Needs plan",
            "yellow",
            "Watchlist candidates with complete entry-plan fields.",
            f"{report.entry_plans.incomplete_plans} plan(s) are incomplete.",
            "Use Morning Review to add trigger, stop, invalidation, and max loss.",
            "",
        )
    return daily_workflow_step(
        "plans",
        "Watchlist Plans",
        "complete",
        "Complete",
        "green",
        "All Watchlist candidates have complete plan discipline.",
        "None.",
        f"{report.entry_plans.complete_plans} Watchlist plan(s) are complete.",
        "",
    )


def daily_workflow_report_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "A reviewable workflow and Watchlist candidates.",
            context.block_reason or context.guidance or "This view is read-only.",
            "report",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "Morning Review complete.",
            "Review decisions are still incomplete.",
            "report",
        )
    if report.entry_plans.watchlist_candidates == 0:
        return daily_workflow_step(
            "report",
            "Watchlist Report",
            "waiting",
            "Unavailable",
            "gray",
            "At least one candidate marked Watchlist.",
            "No Watchlist candidates are selected.",
            "The existing report action will explain this if clicked.",
            "report",
        )
    if report.entry_plans.incomplete_plans:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "Complete Watchlist Plans.",
            "Entry-plan discipline is incomplete.",
            "report",
        )
    return daily_workflow_step(
        "report",
        "Watchlist Report",
        "attention",
        "Available",
        "yellow",
        "Reviewed candidates and complete Watchlist plans.",
        "None.",
        "Generate the Watchlist Report using the existing safe action.",
        "report",
    )


def daily_workflow_readiness_step(readiness_locked: bool) -> dict[str, str]:
    if readiness_locked:
        return daily_workflow_step(
            "readiness",
            "Readiness Gate",
            "locked",
            "Locked check",
            "gray",
            "Existing outcome-maturity/readiness report.",
            "One or more research/readiness gates are locked.",
            "This is a check/gate only; it does not approve trades or change readiness logic.",
            "readiness",
        )
    return daily_workflow_step(
        "readiness",
        "Readiness Gate",
        "complete",
        "Available check",
        "green",
        "Existing outcome-maturity/readiness report.",
        "None.",
        "Open Readiness Gate as a read-only check; trading decisions still require operator review.",
        "readiness",
    )


def daily_workflow_waiting_step(
    step_id: str,
    name: str,
    dependency: str,
    blocker: str,
    action_key: str = "",
) -> dict[str, str]:
    return daily_workflow_step(
        step_id,
        name,
        "waiting",
        "Waiting",
        "gray",
        dependency,
        blocker,
        "Complete the upstream light before this step becomes available.",
        action_key,
    )


def daily_workflow_step(
    step_id: str,
    name: str,
    level: str,
    status: str,
    light: str,
    dependency: str,
    blocker: str,
    detail: str,
    action_key: str,
) -> dict[str, str]:
    return {
        "id": step_id,
        "name": name,
        "level": level,
        "status": status,
        "light": light,
        "dependency": dependency,
        "blocker": blocker,
        "detail": detail,
        "action_key": action_key,
    }
