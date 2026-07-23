from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.capture_health import (
    CaptureHealthSnapshot,
    CsvStatus,
    latest_capture_failure,
    latest_successful_capture,
)
from momentum_hunter.config import DATA_DIR
from momentum_hunter.daily_workflow import build_daily_workflow_report
from momentum_hunter.daily_workflow_guidance import daily_workflow_next_action, daily_workflow_steps
from momentum_hunter.entry_plans import load_entry_plans
from momentum_hunter.models import Candidate, CaptureSession
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.operator_review import (
    OperatorReviewContext,
    OperatorReviewState,
    blocked_context,
    classify_current_manual_scan,
    classify_scheduled_snapshot,
)
from momentum_hunter.outcome_maturity import OutcomeMaturityReport, build_outcome_maturity_report
from momentum_hunter.review import CandidateIdentity, ReviewStatus, load_review_decisions, make_capture_id
from momentum_hunter.time_utils import CENTRAL_TZ
from momentum_hunter.ui.data_view_state import load_freshness_settings


DAILY_WORKFLOW_SNAPSHOT_SCHEMA_VERSION = 1
DAILY_WORKFLOW_STALE_AFTER_HOURS = 24
EXPECTED_STEP_IDS = ("capture", "review", "plans", "report", "readiness")


@dataclass(frozen=True)
class WorkstationDailyWorkflowPaths:
    data_dir: Path
    reports_dir: Path
    captures_dir: Path
    failures_dir: Path
    analysis_csv: Path
    outcomes_csv: Path
    review_decisions_path: Path
    entry_plans_path: Path
    score_breakdowns_path: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path = DATA_DIR) -> WorkstationDailyWorkflowPaths:
        return cls(
            data_dir=data_dir,
            reports_dir=data_dir / "reports",
            captures_dir=data_dir / "captures",
            failures_dir=data_dir / "capture-failures",
            analysis_csv=data_dir / "analysis-captures.csv",
            outcomes_csv=data_dir / "analysis-outcomes.csv",
            review_decisions_path=data_dir / "review-decisions.json",
            entry_plans_path=data_dir / "entry-plans.json",
            score_breakdowns_path=data_dir / "score-breakdowns.json",
        )


def build_daily_workflow_snapshot(
    *,
    paths: WorkstationDailyWorkflowPaths | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Project persisted Daily Workflow evidence without mutating or refreshing it."""

    paths = paths or WorkstationDailyWorkflowPaths.from_data_dir()
    observed_at = as_utc(observed_at or datetime.now(timezone.utc))
    report_path = latest_trade_report_path(paths.reports_dir)
    if report_path is None:
        return unavailable_snapshot(
            observed_at,
            "No persisted trade-planning report is available, so a candidate-specific Daily Workflow cannot be established.",
        )

    report_payload = load_json_object(report_path)
    if report_payload is None:
        return unavailable_snapshot(
            observed_at,
            f"The persisted trade-planning report '{report_path.name}' is unreadable or is not a JSON object.",
            source_label=report_path.name,
        )
    source_rows = report_payload.get("candidates")
    if not isinstance(source_rows, list):
        return unavailable_snapshot(
            observed_at,
            f"The persisted trade-planning report '{report_path.name}' has no valid candidate collection.",
            source_label=report_path.name,
        )

    warnings: list[str] = []
    partial = False
    metadata = object_value(report_payload, "metadata")
    source_as_of = parse_timestamp(metadata.get("generated_at"))
    if source_as_of is None:
        source_as_of = file_timestamp(report_path)
        warnings.append("The source report has no valid generated timestamp; file time is shown instead.")
        partial = True
    capture_time = parse_timestamp(metadata.get("source_capture_time"))
    capture_date = capture_time.astimezone(CENTRAL_TZ).date().isoformat() if capture_time else ""
    session = text_value(metadata.get("source_session")).lower()
    provider = text_value(metadata.get("source_provider"))
    scanner = text_value(metadata.get("source_scanner"))
    if not all((capture_time, capture_date, session, provider, scanner)):
        warnings.append("The source report has incomplete capture identity; review and plan matches may be unavailable.")
        partial = True

    candidates: list[Candidate] = []
    identities: dict[str, CandidateIdentity] = {}
    seen_symbols: set[str] = set()
    malformed_rows = 0
    for row in source_rows:
        if not isinstance(row, dict):
            malformed_rows += 1
            continue
        symbol = text_value(row.get("symbol")).upper()
        if not symbol or symbol in seen_symbols:
            malformed_rows += 1
            continue
        seen_symbols.add(symbol)
        candidates.append(Candidate(ticker=symbol, company=text_value(row.get("company"))))
        if all((capture_date, session, provider, scanner)):
            identities[symbol] = CandidateIdentity(
                capture_id=make_capture_id(capture_date, session, provider, scanner),
                capture_date=capture_date,
                session=session,
                provider=provider,
                scanner=scanner,
                ticker=symbol,
            )
    if malformed_rows:
        warnings.append(f"{malformed_rows} malformed or duplicate candidate row(s) were excluded.")
        partial = True

    review_statuses: dict[str, ReviewStatus] = {}
    if not paths.review_decisions_path.exists():
        warnings.append("Review decisions are unavailable; source candidates are treated as unreviewed.")
        partial = True
    else:
        try:
            review_statuses = {
                key: decision.review_status
                for key, decision in load_review_decisions(paths.review_decisions_path).items()
            }
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            warnings.append("Review decisions are unreadable; source candidates are treated as unreviewed.")
            partial = True

    entry_plans = {}
    if not paths.entry_plans_path.exists():
        warnings.append("Entry-plan evidence is unavailable.")
        partial = True
    else:
        try:
            entry_plans = load_entry_plans(paths.entry_plans_path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            warnings.append("Entry-plan evidence is unreadable.")
            partial = True

    capture_health = build_read_only_capture_health(paths, observed_at)
    try:
        outcome_maturity = build_outcome_maturity_report(
            captures_csv=paths.analysis_csv,
            outcomes_csv=paths.outcomes_csv,
            captures_dir=paths.captures_dir,
            score_breakdowns_path=paths.score_breakdowns_path,
            review_decisions_path=paths.review_decisions_path,
        )
    except (csv.Error, json.JSONDecodeError, OSError, TypeError, ValueError):
        outcome_maturity = unavailable_outcome_maturity()
        warnings.append("Outcome maturity evidence is unreadable; readiness statuses are unavailable.")
        partial = True

    report = build_daily_workflow_report(
        candidates=candidates,
        identities=identities,
        review_statuses=review_statuses,
        entry_plans=entry_plans,
        capture_health=capture_health,
        outcome_maturity=outcome_maturity,
    )
    capture_payload = load_source_capture(paths, capture_date, session)
    if capture_payload is None:
        warnings.append("The source capture could not be read; review context uses report metadata only.")
        partial = True
    context = build_operator_context(
        capture_time=capture_time,
        session=session,
        candidates_loaded=bool(candidates),
        capture_payload=capture_payload,
        observed_at=observed_at,
    )
    next_action = daily_workflow_next_action(report, context)
    steps = daily_workflow_steps(report, context, next_action)

    age_hours = max(0.0, (observed_at - source_as_of).total_seconds() / 3600) if source_as_of else 0.0
    if source_as_of and age_hours > DAILY_WORKFLOW_STALE_AFTER_HOURS:
        warnings.append(
            f"The source report is {age_hours:.1f} hours old, beyond the {DAILY_WORKFLOW_STALE_AFTER_HOURS}-hour evidence window."
        )
    state = (
        "PARTIAL"
        if partial
        else "EMPTY"
        if not candidates
        else "STALE"
        if age_hours > DAILY_WORKFLOW_STALE_AFTER_HOURS
        else "AVAILABLE"
    )
    source_context = " / ".join(value for value in (capture_date, session, provider, scanner) if value)
    summary = (
        f"{state} | Read-only Daily Workflow projection for {len(candidates)} persisted candidate(s). "
        "Workflow lights describe operator discipline, not trade quality or approval."
    )
    return {
        "schemaVersion": DAILY_WORKFLOW_SNAPSHOT_SCHEMA_VERSION,
        "state": state,
        "observedAt": timestamp_text(observed_at),
        "sourceAsOf": timestamp_text(source_as_of) if source_as_of else None,
        "sourceLabel": report_path.name,
        "sourceContext": source_context or "Capture identity unavailable",
        "operatorContextState": context.state.value,
        "operatorContextLabel": context.label,
        "summary": summary,
        "workflowScore": report.workflow_score,
        "captureStatus": report.capture_health_status,
        "review": {
            "total": report.review.total_candidates,
            "reviewed": report.review.reviewed_candidates,
            "unreviewed": report.review.unreviewed_candidates,
            "interested": report.review.interested_candidates,
            "rejected": report.review.rejected_candidates,
            "watchlist": report.review.watchlist_candidates,
        },
        "plans": {
            "watchlist": report.entry_plans.watchlist_candidates,
            "complete": report.entry_plans.complete_plans,
            "incomplete": report.entry_plans.incomplete_plans,
            "missingTrigger": report.entry_plans.missing_trigger,
            "missingStop": report.entry_plans.missing_stop,
            "missingInvalidation": report.entry_plans.missing_invalidation,
            "missingMaxLoss": report.entry_plans.missing_max_loss,
            "withoutPlan": report.entry_plans.watchlist_without_plan,
        },
        "outcomes": {
            "completedNextDay": report.completed_next_day_outcomes,
            "completedFiveDay": report.completed_five_day_outcomes,
            "pending": report.pending_outcomes,
        },
        "readiness": [
            {"name": name, "status": status}
            for name, status in report.readiness_statuses.items()
        ],
        "nextAction": {
            "title": next_action["title"],
            "detail": next_action["detail"],
            "level": next_action["level"],
        },
        "steps": [
            {
                "id": step["id"],
                "name": step["name"],
                "level": step["level"],
                "status": step["status"],
                "light": step["light"],
                "dependency": step["dependency"],
                "blocker": step["blocker"],
                "detail": step["detail"],
            }
            for step in steps
        ],
        "warnings": unique([*warnings, *report.warnings, *outcome_maturity.warnings]),
        "readOnly": True,
    }


def build_read_only_capture_health(
    paths: WorkstationDailyWorkflowPaths,
    observed_at: datetime,
) -> CaptureHealthSnapshot:
    current = observed_at.astimezone(CENTRAL_TZ)
    return CaptureHealthSnapshot(
        last_morning_capture=latest_successful_capture(CaptureSession.MORNING, paths.captures_dir),
        last_evening_capture=latest_successful_capture(CaptureSession.EVENING, paths.captures_dir),
        last_preopen_capture=latest_successful_capture(CaptureSession.PREOPEN, paths.captures_dir),
        last_failed_capture=latest_capture_failure(paths.failures_dir),
        next_morning_run=current,
        next_evening_run=current,
        next_preopen_run=current,
        csv_append_status=read_only_csv_status(paths.analysis_csv),
        outcome_update_status=read_only_csv_status(paths.outcomes_csv),
    )


def read_only_csv_status(path: Path) -> CsvStatus:
    if not path.exists():
        return CsvStatus(path=path, exists=False)
    try:
        with path.open(newline="", encoding="utf-8") as file:
            row_count = sum(1 for _ in csv.DictReader(file))
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, CENTRAL_TZ)
    except (csv.Error, OSError):
        return CsvStatus(path=path, exists=True)
    return CsvStatus(path=path, exists=True, row_count=row_count, last_updated=updated_at)


def build_operator_context(
    *,
    capture_time: datetime | None,
    session: str,
    candidates_loaded: bool,
    capture_payload: dict[str, Any] | None,
    observed_at: datetime,
) -> OperatorReviewContext:
    freshness_minutes = load_freshness_settings().current_dashboard_stale_minutes
    if session == "live":
        return classify_current_manual_scan(
            capture_time=capture_time,
            candidates_loaded=candidates_loaded,
            freshness_threshold_minutes=freshness_minutes,
            now=observed_at,
        )
    if session in {CaptureSession.EVENING.value, CaptureSession.PREOPEN.value}:
        return classify_scheduled_snapshot(
            capture_time=capture_time,
            session=session,
            next_market_session_date=text_value((capture_payload or {}).get("next_market_session_date")),
            freshness_threshold_minutes=freshness_minutes,
            now=observed_at,
            quarantined=text_value((capture_payload or {}).get("capture_status")).lower() == "quarantined",
        )
    if capture_time is None or not candidates_loaded:
        return blocked_context(
            OperatorReviewState.CAPTURE_MISSING,
            "Capture Missing",
            "The persisted candidate context is incomplete and cannot support daily review.",
        )
    return blocked_context(
        OperatorReviewState.HISTORICAL_READ_ONLY,
        "Historical Snapshot - Read Only",
        "This persisted workflow is historical and cannot be used for a new watchlist.",
    )


def load_source_capture(
    paths: WorkstationDailyWorkflowPaths,
    capture_date: str,
    session: str,
) -> dict[str, Any] | None:
    if not capture_date or not session or not session.replace("_", "").isalnum():
        return None
    return load_json_object(paths.captures_dir / capture_date / f"{session}.json")


def unavailable_snapshot(
    observed_at: datetime,
    summary: str,
    *,
    source_label: str = "Daily Workflow source unavailable",
) -> dict[str, Any]:
    return {
        "schemaVersion": DAILY_WORKFLOW_SNAPSHOT_SCHEMA_VERSION,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "sourceAsOf": None,
        "sourceLabel": source_label,
        "sourceContext": "Capture identity unavailable",
        "operatorContextState": OperatorReviewState.CAPTURE_MISSING.value,
        "operatorContextLabel": "Capture Missing",
        "summary": f"UNAVAILABLE | {summary}",
        "workflowScore": 0,
        "captureStatus": "unavailable",
        "review": zero_review_counts(),
        "plans": zero_plan_counts(),
        "outcomes": {"completedNextDay": 0, "completedFiveDay": 0, "pending": 0},
        "readiness": [],
        "nextAction": {
            "title": "Next Required Action: restore persisted workflow evidence",
            "detail": summary,
            "level": "blocked",
        },
        "steps": [],
        "warnings": [summary],
        "readOnly": True,
    }


def unavailable_outcome_maturity() -> OutcomeMaturityReport:
    return OutcomeMaturityReport(
        label="Outcome maturity unavailable",
        source="Unreadable persisted evidence",
        filters=None,
        total_candidates=0,
        study_eligible_candidates=0,
        completed_next_day_outcomes=0,
        completed_five_day_outcomes=0,
        pending_next_day_outcomes=0,
        pending_five_day_outcomes=0,
        completed_outcome_pct=0.0,
        pending_outcome_pct=0.0,
        earliest_capture_date="n/a",
        latest_capture_date="n/a",
        earliest_date_with_usable_five_day_outcomes="n/a",
        latest_date_with_pending_five_day_outcomes="n/a",
        gates=[],
        warnings=["OUTCOME MATURITY UNAVAILABLE"],
    )


def zero_review_counts() -> dict[str, int]:
    return {"total": 0, "reviewed": 0, "unreviewed": 0, "interested": 0, "rejected": 0, "watchlist": 0}


def zero_plan_counts() -> dict[str, int]:
    return {
        "watchlist": 0,
        "complete": 0,
        "incomplete": 0,
        "missingTrigger": 0,
        "missingStop": 0,
        "missingInvalidation": 0,
        "missingMaxLoss": 0,
        "withoutPlan": 0,
    }


def load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def object_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def parse_timestamp(value: object) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        return as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def file_timestamp(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def text_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
