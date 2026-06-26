from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH, load_active_monitor_status
from momentum_hunter.active_alert_reliability import ACTIVE_ALERT_RELIABILITY_LATEST_JSON
from momentum_hunter.capture_health import build_capture_health_snapshot
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DataQualityReport, build_data_quality_report, load_latest_data_quality_report
from momentum_hunter.entry_plans import load_entry_plans
from momentum_hunter.evidence_autopilot_reliability import (
    EvidenceAutopilotReliabilityReport,
    build_evidence_autopilot_reliability_report,
    load_latest_evidence_autopilot_reliability_report,
)
from momentum_hunter.evidence_health import EvidenceHealthReport, build_evidence_health_report
from momentum_hunter.review import ReviewStatus, load_review_decisions
from momentum_hunter.sqlite_reports import REPORTS_DIR as SQLITE_REPORTS_DIR
from momentum_hunter.sqlite_validation import SQLITE_VALIDATION_LATEST_JSON
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR
from momentum_hunter.time_utils import now_central
from momentum_hunter.user_state_diff import USER_STATE_DIFF_LATEST_JSON


SYSTEM_READINESS_SCHEMA_VERSION = 1
SYSTEM_READINESS_ENGINE_VERSION = "system_readiness_v1"
SYSTEM_READINESS_LATEST_JSON = DATA_DIR / "reports" / "system-readiness-latest.json"
SYSTEM_READINESS_LATEST_MD = DATA_DIR / "reports" / "system-readiness-latest.md"
OUTCOMES_CSV = DATA_DIR / "analysis-outcomes.csv"
SCORE_BREAKDOWNS_PATH = DATA_DIR / "score-breakdowns.json"
PROVIDER_FIELD_QUALITY_LATEST_JSON = DATA_DIR / "reports" / "provider-field-quality-latest.json"
STALE_SYSTEM_SIGNAL_MINUTES = 24 * 60


@dataclass(frozen=True)
class ReadinessSection:
    name: str
    status: str
    explanation: str
    supporting_facts: list[str] = field(default_factory=list)
    recommended_next_action: str = ""


@dataclass(frozen=True)
class SystemReadinessReport:
    generated_at: str
    overall_status: str
    status_reason: str
    highest_priority_issue: str
    recommended_next_action: str
    section_status_counts: dict[str, int]
    changes_since_previous: list[str]
    sections: list[ReadinessSection]
    issues_requiring_attention: list[str]
    warnings: list[str] = field(default_factory=list)


def build_system_readiness_report(
    *,
    data_quality_report: DataQualityReport | None = None,
    autopilot_report: EvidenceAutopilotReliabilityReport | None = None,
    evidence_health_report: EvidenceHealthReport | None = None,
    generated_at: datetime | None = None,
    previous_report_path: Path | None = SYSTEM_READINESS_LATEST_JSON,
) -> SystemReadinessReport:
    generated_at = generated_at or now_central()
    data_quality = data_quality_report or load_latest_data_quality_report()
    autopilot = autopilot_report or load_latest_evidence_autopilot_reliability_report()
    health = evidence_health_report or build_evidence_health_report(generated_at=generated_at)
    sections = [
        market_data_section(data_quality),
        scanner_section(),
        captures_section(),
        watchlist_section(),
        active_monitor_section(generated_at=generated_at),
        evidence_autopilot_section(autopilot),
        active_alert_reliability_section(),
        outcome_tracking_section(health),
        research_data_section(),
        storage_integrity_section(),
        sqlite_mirror_section(generated_at=generated_at),
        provider_field_quality_section(),
        user_state_safety_section(),
        schedules_section(),
    ]
    top_issue = highest_priority_issue(sections)
    status = overall_status(sections)
    previous = load_json(previous_report_path) if previous_report_path else {}
    issues = [
        f"{section.name}: {section.explanation}"
        for section in sections
        if section.status in {"FAILED", "WARNING", "UNKNOWN"}
    ]
    warnings = [warning for section in sections for warning in section.supporting_facts if warning.startswith("WARNING:")]
    return SystemReadinessReport(
        generated_at=generated_at.isoformat(),
        overall_status=status,
        status_reason=status_reason(status, top_issue),
        highest_priority_issue=top_issue,
        recommended_next_action=recommended_next_action_for_issue(sections, top_issue),
        section_status_counts=section_status_counts(sections),
        changes_since_previous=changes_since_previous(sections, status, previous),
        sections=sections,
        issues_requiring_attention=issues,
        warnings=warnings,
    )


def market_data_section(report: DataQualityReport | None) -> ReadinessSection:
    if report is None:
        return ReadinessSection(
            name="Market Data",
            status="UNKNOWN",
            explanation="No latest data-quality report exists yet.",
            supporting_facts=["Run python -m momentum_hunter.data_quality to create data-quality-latest.json/md."],
            recommended_next_action="Generate the data-quality report before trusting live monitor decisions.",
        )
    if report.symbol_count == 0:
        return ReadinessSection(
            name="Market Data",
            status="UNKNOWN",
            explanation="No symbols were available for market-data validation.",
            supporting_facts=list(report.warnings),
            recommended_next_action="Add monitor targets or run a scan so market data can be audited.",
        )
    status = "READY" if report.missing_market_tape_count == 0 else "WARNING"
    if report.usable_market_tape_count == 0:
        status = "FAILED"
    return ReadinessSection(
        name="Market Data",
        status=status,
        explanation=f"{report.usable_market_tape_count} of {report.symbol_count} symbols have usable market tape.",
        supporting_facts=[
            f"Missing market tape: {report.missing_market_tape_count}",
            f"Warnings: {', '.join(report.warnings) if report.warnings else 'none'}",
        ],
        recommended_next_action="Fix provider/data gaps before relying on active alerts." if status != "READY" else "Market tape is usable for monitored symbols.",
    )


def scanner_section() -> ReadinessSection:
    path = latest_capture_path()
    if path is None:
        return ReadinessSection(
            name="Scanner",
            status="UNKNOWN",
            explanation="No capture JSON files were found.",
            recommended_next_action="Run or wait for the next scheduled capture.",
        )
    payload = load_json(path)
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    provider = payload.get("provider", "") if isinstance(payload, dict) else ""
    scanner = payload.get("scanner", {}) if isinstance(payload, dict) else {}
    scanner_name = scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)
    status = "READY" if candidates else "WARNING"
    return ReadinessSection(
        name="Scanner",
        status=status,
        explanation=f"Latest capture has {len(candidates)} candidate(s).",
        supporting_facts=[f"Latest capture: {path}", f"Provider: {provider}", f"Scanner: {scanner_name}"],
        recommended_next_action="Review the latest candidates." if candidates else "Run scanner or inspect provider status.",
    )


def captures_section() -> ReadinessSection:
    snapshot = build_capture_health_snapshot()
    facts = [
        f"Last morning: {capture_fact(snapshot.last_morning_capture)}",
        f"Last evening: {capture_fact(snapshot.last_evening_capture)}",
        f"Last preopen: {capture_fact(snapshot.last_preopen_capture)}",
        f"CSV rows: {snapshot.csv_append_status.row_count if snapshot.csv_append_status.exists else 'missing'}",
        f"Outcome rows: {snapshot.outcome_update_status.row_count if snapshot.outcome_update_status.exists else 'missing'}",
    ]
    status = "READY"
    explanation = "Scheduled capture records are present."
    if snapshot.last_failed_capture.path:
        status = "WARNING"
        explanation = "A capture failure record exists."
        facts.append(f"WARNING: Last failure: {snapshot.last_failed_capture.path}")
    if not snapshot.last_morning_capture.path and not snapshot.last_evening_capture.path and not snapshot.last_preopen_capture.path:
        status = "FAILED"
        explanation = "No successful captures were found."
    return ReadinessSection(
        name="Captures",
        status=status,
        explanation=explanation,
        supporting_facts=facts,
        recommended_next_action="Open Capture Health for failure details." if status != "READY" else "Captures are available for review.",
    )


def watchlist_section() -> ReadinessSection:
    decisions = load_review_decisions()
    plans = load_entry_plans()
    interested = sum(1 for item in decisions.values() if item.review_status == ReviewStatus.INTERESTED)
    watchlist = sum(1 for item in decisions.values() if item.review_status == ReviewStatus.WATCHLIST)
    complete_plans = sum(1 for item in plans.values() if item.plan_complete)
    incomplete_plans = max(0, len(plans) - complete_plans)
    status = "READY" if watchlist or interested or plans else "WARNING"
    return ReadinessSection(
        name="Watchlist State",
        status=status,
        explanation=f"{interested} interested, {watchlist} watchlist, {len(plans)} entry plan(s).",
        supporting_facts=[
            f"Complete plans: {complete_plans}",
            f"Incomplete plans: {incomplete_plans}",
        ],
        recommended_next_action="Open Watchlist Center or Morning Review to finish plans." if incomplete_plans else "Watchlist state is available.",
    )


def active_monitor_section(
    *,
    generated_at: datetime | None = None,
    status_path: Path = ACTIVE_MONITOR_STATUS_PATH,
) -> ReadinessSection:
    generated_at = generated_at or now_central()
    status = load_active_monitor_status(status_path)
    if status is None:
        return ReadinessSection(
            name="Active Monitor",
            status="UNKNOWN",
            explanation="No active-monitor status file exists.",
            recommended_next_action="Run a monitor cycle to create an active-monitor status baseline.",
        )
    section_status = "READY"
    if status.state == "FAILED":
        section_status = "FAILED"
    elif status.warnings:
        section_status = "WARNING"
    cycle_age = timestamp_age_minutes(status.last_cycle_at, generated_at)
    stale = bool(cycle_age is not None and cycle_age > STALE_SYSTEM_SIGNAL_MINUTES)
    if stale and section_status == "READY":
        section_status = "WARNING"
    facts = [
        f"Last cycle: {status.last_cycle_at or 'n/a'}",
        f"Last cycle age minutes: {round(cycle_age, 2) if cycle_age is not None else 'unknown'}",
        f"Last report: {status.last_report_path or 'n/a'}",
        f"Warnings: {', '.join(status.warnings) if status.warnings else 'none'}",
        f"Last error: {status.last_error or 'none'}",
    ]
    if stale:
        facts.append("WARNING: STALE_ACTIVE_MONITOR_CYCLE")
    return ReadinessSection(
        name="Active Monitor",
        status=section_status,
        explanation=f"Monitor status is {status.state}; completed {status.cycles_completed} of {status.cycles_requested} requested cycle(s).",
        supporting_facts=facts,
        recommended_next_action=(
            "Fix active monitor failure before trusting alerts."
            if section_status == "FAILED"
            else "Run a fresh active monitor cycle before trusting current alert state."
            if stale
            else "Active monitor status is recorded."
        ),
    )


def evidence_autopilot_section(report: EvidenceAutopilotReliabilityReport | None) -> ReadinessSection:
    if report is None:
        return ReadinessSection(
            name="Evidence Autopilot",
            status="UNKNOWN",
            explanation="No evidence-autopilot latest report exists.",
            supporting_facts=["Run python -m momentum_hunter.evidence_autopilot_reliability."],
            recommended_next_action="Generate the autopilot reliability report.",
        )
    status = "READY"
    if report.latest_run_state == "FAILED":
        status = "FAILED"
    elif report.warnings or not report.monitor_cycle_completed or not report.outcome_update_completed:
        status = "WARNING"
    facts = [
        f"Targets checked: {report.targets_checked}",
        f"Latest run age minutes: {round(report.latest_run_age_minutes, 2) if report.latest_run_age_minutes is not None else 'unknown'}",
        f"Latest run stale: {report.latest_run_stale}",
        f"Completed alerts: {report.completed_alerts}",
        f"Pending alerts: {report.pending_alerts}",
        f"Unscorable alerts: {report.unscorable_alerts}",
        f"Warnings: {', '.join(report.warnings) if report.warnings else 'none'}",
    ]
    if report.latest_run_stale:
        facts.append("WARNING: STALE_EVIDENCE_AUTOPILOT_RUN")
    return ReadinessSection(
        name="Evidence Autopilot",
        status=status,
        explanation=f"Autopilot latest state: {report.latest_run_state}; execution mode: {report.execution_mode}.",
        supporting_facts=facts,
        recommended_next_action=report.next_recommended_action,
    )


def active_alert_reliability_section(path: Path = ACTIVE_ALERT_RELIABILITY_LATEST_JSON) -> ReadinessSection:
    payload = load_json(path)
    report = payload.get("report", payload) if payload else {}
    if not isinstance(report, dict) or not report:
        return ReadinessSection(
            name="Active Alert Reliability",
            status="UNKNOWN",
            explanation="No latest active-alert reliability report exists.",
            supporting_facts=[f"Report path: {path}"],
            recommended_next_action="Run python -m momentum_hunter.active_alert_reliability.",
        )
    report_status = str(report.get("overall_status", "UNKNOWN"))
    warnings = [str(item) for item in report.get("warnings", [])] if isinstance(report.get("warnings"), list) else []
    status = "READY" if report_status == "READY" and not warnings else "WARNING"
    if report_status == "FAILED":
        status = "FAILED"
    return ReadinessSection(
        name="Active Alert Reliability",
        status=status,
        explanation=f"Active-alert reliability status is {report_status}.",
        supporting_facts=[
            f"Active monitor state: {report.get('active_monitor_state', 'UNKNOWN')}",
            f"Latest cycle age minutes: {report.get('active_monitor_cycle_age_minutes', 'unknown')}",
            f"Alerts: {report.get('alert_count', 0)}",
            f"Completed alerts: {report.get('completed_alert_count', 0)}",
            f"Pending alerts: {report.get('pending_alert_count', 0)}",
            f"Unscorable alerts: {report.get('unscorable_alert_count', 0)}",
            f"Warnings: {', '.join(warnings) if warnings else 'none'}",
        ],
        recommended_next_action=str(report.get("next_recommended_action") or "Review active-alert reliability warnings."),
    )


def outcome_tracking_section(report: EvidenceHealthReport) -> ReadinessSection:
    status = "READY" if report.completed_alerts else "WARNING"
    if report.pending_alerts or report.unscorable_alerts or report.warnings:
        status = "WARNING"
    return ReadinessSection(
        name="Outcome Tracking",
        status=status,
        explanation=f"{report.completed_alerts} completed, {report.pending_alerts} pending, {report.unscorable_alerts} unscorable alert(s).",
        supporting_facts=[
            f"Evidence status: {report.evidence_gate.evidence_status}",
            f"Strategy optimization: {report.evidence_gate.strategy_optimization_status}",
            f"Warnings: {', '.join(report.warnings) if report.warnings else 'none'}",
        ],
        recommended_next_action="Continue collecting completed alert outcomes; optimization remains gated.",
    )


def research_data_section() -> ReadinessSection:
    facts = [
        f"analysis-captures.csv exists: {ANALYSIS_CSV.exists()}",
        f"analysis-outcomes.csv exists: {OUTCOMES_CSV.exists()}",
        f"score-breakdowns.json exists: {SCORE_BREAKDOWNS_PATH.exists()}",
    ]
    status = "READY" if ANALYSIS_CSV.exists() and OUTCOMES_CSV.exists() else "WARNING"
    return ReadinessSection(
        name="Research Data",
        status=status,
        explanation="Derived research stores are present." if status == "READY" else "One or more derived research stores are missing.",
        supporting_facts=facts,
        recommended_next_action="Rebuild derived analysis data if research tables look stale." if status != "READY" else "Research data stores are available.",
    )


def storage_integrity_section() -> ReadinessSection:
    capture_count = len(list(CAPTURES_DIR.glob("*/*.json"))) if CAPTURES_DIR.exists() else 0
    manifest_exists = CAPTURE_INTEGRITY_MANIFEST.exists()
    status = "READY" if capture_count and manifest_exists else "WARNING"
    return ReadinessSection(
        name="Storage Integrity",
        status=status,
        explanation="Raw captures and integrity manifest are present." if status == "READY" else "Integrity metadata is incomplete or no captures are present.",
        supporting_facts=[
            f"Raw capture JSON files: {capture_count}",
            f"Manifest exists: {manifest_exists}",
            f"Manifest path: {CAPTURE_INTEGRITY_MANIFEST}",
        ],
        recommended_next_action="Run python -m momentum_hunter.integrity_audit for a full hash audit." if status != "READY" else "Run integrity audit if trust is in question.",
    )


def sqlite_mirror_section(
    *,
    validation_path: Path = SQLITE_VALIDATION_LATEST_JSON,
    shadow_compare_path: Path = SQLITE_REPORTS_DIR / "sqlite-shadow-compare-latest.json",
    generated_at: datetime | None = None,
) -> ReadinessSection:
    generated_at = generated_at or now_central()
    validation = load_json(validation_path)
    shadow = load_json(shadow_compare_path)
    if not validation:
        return ReadinessSection(
            name="SQLite Mirror",
            status="UNKNOWN",
            explanation="No latest SQLite validation report exists.",
            supporting_facts=[
                f"Validation report path: {validation_path}",
                f"Shadow compare path: {shadow_compare_path}",
            ],
            recommended_next_action="Run python -m momentum_hunter.sqlite_validation before trusting SQLite read models.",
        )

    validation_status = str(validation.get("overall_status", "UNKNOWN"))
    shadow_status = str(shadow.get("overall_status", "UNKNOWN")) if shadow else "MISSING"
    mismatches = int_value(shadow.get("mismatches")) if shadow else 0
    unavailable = int_value(shadow.get("unavailable")) if shadow else 0
    missing_slices = validation.get("missing_slices", [])
    validation_warnings = validation.get("warnings", [])
    shadow_warnings = shadow.get("warnings", []) if shadow else []
    latest_import_age = latest_import_age_minutes(validation, generated_at)
    stale_sqlite = bool(latest_import_age is not None and latest_import_age > STALE_SYSTEM_SIGNAL_MINUTES)
    status = "READY"
    if validation_status == "FAIL":
        status = "FAILED"
    elif validation_status != "PASS" or shadow_status != "PASS" or mismatches or unavailable or missing_slices or stale_sqlite:
        status = "WARNING"
    explanation = (
        "SQLite mirrors match file-authoritative sources."
        if status == "READY"
        else "SQLite mirror validation or shadow comparison requires attention."
    )
    facts = [
        f"Validation status: {validation_status}",
        f"Shadow compare status: {shadow_status}",
        f"Schema version: {validation.get('sqlite_schema_version', 'n/a')}",
        f"Missing slices: {', '.join(str(item) for item in missing_slices) if missing_slices else 'none'}",
        f"Shadow mismatches: {mismatches}",
        f"Unavailable shadow fields: {unavailable}",
        f"Latest import age minutes: {round(latest_import_age, 2) if latest_import_age is not None else 'unknown'}",
        f"Validation warnings: {', '.join(str(item) for item in validation_warnings) if validation_warnings else 'none'}",
        f"Shadow warnings: {', '.join(str(item) for item in shadow_warnings) if shadow_warnings else 'none'}",
    ]
    if stale_sqlite:
        facts.append("WARNING: STALE_SQLITE_MIRROR")
    return ReadinessSection(
        name="SQLite Mirror",
        status=status,
        explanation=explanation,
        supporting_facts=facts,
        recommended_next_action=(
            "Keep file fallback active and rerun SQLite imports/validation before using SQLite read models."
            if status != "READY"
            else "SQLite mirror is safe for diagnostic read-only reports; file sources remain authoritative."
        ),
    )


def provider_field_quality_section(path: Path = PROVIDER_FIELD_QUALITY_LATEST_JSON) -> ReadinessSection:
    payload = load_json(path)
    if not payload:
        return ReadinessSection(
            name="Provider Field Quality",
            status="UNKNOWN",
            explanation="No provider-field-quality report exists.",
            supporting_facts=[f"Report path: {path}"],
            recommended_next_action="Run python -m momentum_hunter.provider_field_quality.",
        )
    report_status = str(payload.get("overall_status", "UNKNOWN"))
    status = "READY" if report_status == "PASS" else "WARNING"
    if report_status == "FAIL":
        status = "FAILED"
    top_warnings = payload.get("top_warnings", []) if isinstance(payload.get("top_warnings"), list) else []
    warning_text = ", ".join(
        f"{item.get('warning')}:{item.get('count')}" for item in top_warnings[:5] if isinstance(item, dict)
    )
    return ReadinessSection(
        name="Provider Field Quality",
        status=status,
        explanation=f"Provider field quality status is {report_status}.",
        supporting_facts=[
            f"Source rows: {payload.get('source_rows', 0)}",
            f"Audit rows: {payload.get('audit_row_count', 0)}",
            f"SQLite write status: {payload.get('sqlite_write_status', {}).get('status', 'UNKNOWN')}",
            f"Top warnings: {warning_text or 'none'}",
            f"Report warnings: {', '.join(str(item) for item in payload.get('warnings', [])) if payload.get('warnings') else 'none'}",
        ],
        recommended_next_action=(
            "Review provider-field warnings before trusting scanner-relative-volume or stale capture-derived fields."
            if status != "READY"
            else "Provider field quality report is clean."
        ),
    )


def user_state_safety_section(*, diff_path: Path = USER_STATE_DIFF_LATEST_JSON) -> ReadinessSection:
    diff = load_json(diff_path)
    if not diff:
        return ReadinessSection(
            name="User-State Safety",
            status="UNKNOWN",
            explanation="No latest SQLite user-state diff report exists.",
            supporting_facts=[f"Diff report path: {diff_path}"],
            recommended_next_action="Run python -m momentum_hunter.sqlite_validation --slice user-state.",
        )
    diff_status = str(diff.get("overall_status", "UNKNOWN"))
    missing = int_value(diff.get("missing_in_sqlite"))
    extra = int_value(diff.get("extra_in_sqlite"))
    changed = int_value(diff.get("changed_values"))
    malformed = int_value(diff.get("malformed_records"))
    warnings = diff.get("warnings", [])
    status = "READY" if diff_status == "PASS" and not missing and not extra and not changed and not warnings else "WARNING"
    return ReadinessSection(
        name="User-State Safety",
        status=status,
        explanation=(
            "File-authoritative user state matches the SQLite mirror."
            if status == "READY"
            else "File-authoritative user state and SQLite mirror need review."
        ),
        supporting_facts=[
            f"Diff status: {diff_status}",
            f"Records in files: {diff.get('records_in_files', 0)}",
            f"Records in SQLite: {diff.get('records_in_sqlite', 0)}",
            f"Missing in SQLite: {missing}",
            f"Extra in SQLite: {extra}",
            f"Changed values: {changed}",
            f"Malformed records: {malformed}",
            f"Warnings: {', '.join(str(item) for item in warnings) if warnings else 'none'}",
        ],
        recommended_next_action=(
            "Keep files authoritative; rerun user-state import/diff and resolve reported conflicts manually."
            if status != "READY"
            else "User-authored files remain authoritative and match the SQLite mirror."
        ),
    )


def schedules_section() -> ReadinessSection:
    snapshot = build_capture_health_snapshot()
    return ReadinessSection(
        name="Schedules",
        status="READY",
        explanation="Next scheduled capture windows can be calculated from the shared market-calendar policy.",
        supporting_facts=[
            f"Next morning run: {snapshot.next_morning_run.isoformat()}",
            f"Next evening run: {snapshot.next_evening_run.isoformat()}",
            f"Next preopen run: {snapshot.next_preopen_run.isoformat()}",
        ],
        recommended_next_action="Verify Windows Task Scheduler separately if captures stop arriving.",
    )


def overall_status(sections: list[ReadinessSection]) -> str:
    statuses = {section.status for section in sections}
    if "FAILED" in statuses:
        return "FAILED"
    if "WARNING" in statuses:
        return "WARNING"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "READY"


def section_status_counts(sections: list[ReadinessSection]) -> dict[str, int]:
    counts = {"READY": 0, "WARNING": 0, "FAILED": 0, "UNKNOWN": 0}
    for section in sections:
        counts[section.status] = counts.get(section.status, 0) + 1
    return counts


def highest_priority_issue(sections: list[ReadinessSection]) -> str:
    for status in ("FAILED", "WARNING", "UNKNOWN"):
        for section in sections:
            if section.status == status:
                return f"{section.name}: {section.explanation}"
    return "No high-priority issues detected."


def recommended_next_action_for_issue(sections: list[ReadinessSection], issue: str) -> str:
    for section in sections:
        if issue.startswith(f"{section.name}:"):
            return section.recommended_next_action or "Review this section before relying on Momentum Hunter."
    return "No action required. Continue normal evidence collection and review workflow."


def status_reason(status: str, issue: str) -> str:
    if status == "READY":
        return "All readiness sections are ready."
    if status == "FAILED":
        return f"At least one readiness section failed. Highest priority: {issue}"
    if status == "WARNING":
        return f"One or more readiness sections need attention. Highest priority: {issue}"
    return f"One or more readiness sections are unknown. Highest priority: {issue}"


def changes_since_previous(sections: list[ReadinessSection], status: str, previous_payload: dict[str, Any]) -> list[str]:
    previous_report = previous_payload.get("report", previous_payload) if previous_payload else {}
    if not isinstance(previous_report, dict) or not previous_report:
        return ["No previous report available for comparison."]
    changes: list[str] = []
    previous_status = str(previous_report.get("overall_status", ""))
    if previous_status and previous_status != status:
        changes.append(f"Overall status changed: {previous_status} -> {status}")
    previous_sections = {
        str(section.get("name", "")): str(section.get("status", ""))
        for section in previous_report.get("sections", [])
        if isinstance(section, dict)
    }
    for section in sections:
        before = previous_sections.get(section.name)
        if before and before != section.status:
            changes.append(f"{section.name} changed: {before} -> {section.status}")
        elif before is None:
            changes.append(f"{section.name} added with status {section.status}")
    for name in sorted(set(previous_sections) - {section.name for section in sections}):
        changes.append(f"{name} removed from report.")
    return changes or ["No section status changes since previous report."]


def export_system_readiness_report(
    report: SystemReadinessReport,
    *,
    json_path: Path = SYSTEM_READINESS_LATEST_JSON,
    markdown_path: Path = SYSTEM_READINESS_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SYSTEM_READINESS_SCHEMA_VERSION,
        "engine_version": SYSTEM_READINESS_ENGINE_VERSION,
        "report": asdict(report),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_system_readiness_markdown(report), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def format_system_readiness_markdown(report: SystemReadinessReport) -> str:
    lines = [
        f"# Momentum Hunter System Readiness - {report.generated_at}",
        "",
        "Read-only operator trust report. This does not change trading logic or mutate raw captures.",
        "",
        f"**Overall Status:** {report.overall_status}",
        f"**Reason:** {report.status_reason}",
        f"**Highest Priority Issue:** {report.highest_priority_issue}",
        f"**Recommended Next Action:** {report.recommended_next_action}",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status, count in report.section_status_counts.items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Changes Since Previous Report",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in report.changes_since_previous] or ["- None."])
    lines.extend(
        [
            "",
            "## Sections",
            "",
        ]
    )
    for section in report.sections:
        lines.extend(
            [
                f"### {section.name}: {section.status}",
                "",
                section.explanation,
                "",
                "Supporting facts:",
            ]
        )
        lines.extend([f"- {fact}" for fact in section.supporting_facts] or ["- None."])
        lines.extend(["", f"Recommended next action: {section.recommended_next_action or 'n/a'}", ""])
    lines.extend(["## Issues Requiring Attention", ""])
    lines.extend([f"- {issue}" for issue in report.issues_requiring_attention] if report.issues_requiring_attention else ["- None."])
    lines.append("")
    return "\n".join(lines)


def latest_capture_path() -> Path | None:
    if not CAPTURES_DIR.exists():
        return None
    files = list(CAPTURES_DIR.glob("*/*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def timestamp_age_minutes(value: str, generated_at: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None and generated_at.tzinfo is not None:
        parsed = parsed.replace(tzinfo=generated_at.tzinfo)
    return max(0.0, (generated_at - parsed).total_seconds() / 60.0)


def latest_import_age_minutes(validation: dict[str, Any], generated_at: datetime) -> float | None:
    timestamps = validation.get("import_timestamps", {})
    if not isinstance(timestamps, dict):
        return None
    candidates: list[datetime] = []
    for item in timestamps.values():
        if not isinstance(item, dict):
            continue
        value = item.get("latest_imported_at") or item.get("first_imported_at")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        if parsed.tzinfo is None and generated_at.tzinfo is not None:
            parsed = parsed.replace(tzinfo=generated_at.tzinfo)
        candidates.append(parsed)
    if not candidates:
        return None
    return max(0.0, (generated_at - max(candidates)).total_seconds() / 60.0)


def capture_fact(info: object) -> str:
    path = getattr(info, "path", None)
    if not path:
        return "none"
    time_value = getattr(info, "capture_time", None)
    count = getattr(info, "candidate_count", 0)
    return f"{time_value.isoformat() if time_value else 'unknown'} ({count} candidates) {path}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter system-readiness latest reports.")
    parser.add_argument("--refresh-data-quality", action="store_true", help="Build a fresh data-quality report first.")
    parser.add_argument("--refresh-autopilot", action="store_true", help="Build a fresh evidence-autopilot reliability report first.")
    parser.add_argument("--json", type=Path, default=SYSTEM_READINESS_LATEST_JSON)
    parser.add_argument("--md", type=Path, default=SYSTEM_READINESS_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_quality = build_data_quality_report() if args.refresh_data_quality else None
    autopilot = build_evidence_autopilot_reliability_report() if args.refresh_autopilot else None
    report = build_system_readiness_report(data_quality_report=data_quality, autopilot_report=autopilot)
    paths = export_system_readiness_report(report, json_path=args.json, markdown_path=args.md)
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
