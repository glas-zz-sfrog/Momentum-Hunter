from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.active_monitor import latest_monitor_cycle_json_path, load_active_monitor_status
from momentum_hunter.alert_outcome_updater import ALERT_OUTCOME_UPDATE_STATUS_PATH, load_update_report
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.evidence_autopilot import EVIDENCE_AUTOPILOT_STATUS_PATH, load_evidence_autopilot_status
from momentum_hunter.evidence_health import EvidenceHealthReport, build_evidence_health_report
from momentum_hunter.time_utils import now_central


EVIDENCE_AUTOPILOT_RELIABILITY_SCHEMA_VERSION = 1
EVIDENCE_AUTOPILOT_RELIABILITY_VERSION = "evidence_autopilot_reliability_v1"
EVIDENCE_AUTOPILOT_LATEST_JSON = DATA_DIR / "reports" / "evidence-autopilot-latest.json"
EVIDENCE_AUTOPILOT_LATEST_MD = DATA_DIR / "reports" / "evidence-autopilot-latest.md"


@dataclass(frozen=True)
class EvidenceAutopilotReliabilityReport:
    generated_at: str
    autopilot_status_path: str
    latest_run_state: str
    latest_run_started_at: str
    latest_run_completed_at: str
    latest_run_duration_seconds: float | None
    execution_mode: str
    monitor_cycle_completed: bool
    outcome_update_completed: bool
    evidence_report_generated: bool
    daily_brief_generated: bool
    monitor_cycle_path: str
    outcome_status_path: str
    evidence_report_path: str
    daily_brief_path: str
    targets_checked: int
    alerts_added: int
    active_alerts: int
    tracked_alerts: int
    outcomes_updated: int
    completed_alerts: int
    pending_alerts: int
    unscorable_alerts: int
    stale_pending_alerts: int
    missing_minute_bar_alerts: int
    missing_outcome_alerts: int
    warnings: list[str] = field(default_factory=list)
    failure_reason: str = ""
    next_recommended_action: str = ""


def build_evidence_autopilot_reliability_report(
    *,
    status_path: Path = EVIDENCE_AUTOPILOT_STATUS_PATH,
    active_monitor_status_path: Path | None = None,
    outcome_status_path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH,
    reports_dir: Path | None = None,
    evidence_health_report: EvidenceHealthReport | None = None,
    generated_at: datetime | None = None,
) -> EvidenceAutopilotReliabilityReport:
    generated_at = generated_at or now_central()
    reports_dir = reports_dir or DATA_DIR / "reports"
    status = load_evidence_autopilot_status(status_path)
    active_status = load_active_monitor_status(active_monitor_status_path) if active_monitor_status_path else load_active_monitor_status()
    outcome_status = load_update_report(outcome_status_path)
    health = evidence_health_report or build_evidence_health_report(reports_dir=reports_dir, generated_at=generated_at)
    cycle_payload = load_monitor_cycle_payload(status.monitor_cycle_path if status else "", reports_dir=reports_dir)
    targets_checked = parse_int(cycle_payload.get("target_count")) if cycle_payload else 0
    warnings: list[str] = []
    if status is None:
        warnings.append("NO_EVIDENCE_AUTOPILOT_STATUS")
    else:
        warnings.extend(status.warnings)
        if status.last_error:
            warnings.append("EVIDENCE_AUTOPILOT_LAST_RUN_FAILED")
    if active_status and active_status.last_error:
        warnings.append("ACTIVE_MONITOR_LAST_ERROR")
    warnings.extend(health.warnings)
    if outcome_status:
        warnings.extend(outcome_status.warnings)
    else:
        warnings.append("NO_ALERT_OUTCOME_UPDATE_STATUS")
    execution_mode = infer_execution_mode(status, active_status)
    return EvidenceAutopilotReliabilityReport(
        generated_at=generated_at.isoformat(),
        autopilot_status_path=str(status_path),
        latest_run_state=status.state if status else "UNKNOWN",
        latest_run_started_at=status.started_at if status else "",
        latest_run_completed_at=status.completed_at if status else "",
        latest_run_duration_seconds=run_duration_seconds(status.started_at, status.completed_at) if status else None,
        execution_mode=execution_mode,
        monitor_cycle_completed=bool(status and status.monitor_cycle_completed),
        outcome_update_completed=bool(status and status.outcome_update_completed),
        evidence_report_generated=bool(status and status.evidence_report_generated),
        daily_brief_generated=bool(status and status.daily_brief_generated),
        monitor_cycle_path=status.monitor_cycle_path if status else str(latest_monitor_cycle_json_path(reports_dir) or ""),
        outcome_status_path=status.outcome_status_path if status else str(outcome_status_path),
        evidence_report_path=status.evidence_report_path if status else "",
        daily_brief_path=status.daily_brief_path if status else "",
        targets_checked=targets_checked,
        alerts_added=status.new_alert_count if status else 0,
        active_alerts=status.active_alert_count if status else 0,
        tracked_alerts=status.tracked_alert_count if status else 0,
        outcomes_updated=status.updated_outcome_count if status else (outcome_status.updated_alert_count if outcome_status else 0),
        completed_alerts=health.completed_alerts,
        pending_alerts=health.pending_alerts,
        unscorable_alerts=health.unscorable_alerts,
        stale_pending_alerts=len(health.stale_pending_alerts),
        missing_minute_bar_alerts=len(health.missing_minute_bar_alerts),
        missing_outcome_alerts=len(health.missing_outcome_alerts),
        warnings=dedupe(warnings),
        failure_reason=status.last_error if status else "No evidence autopilot status file found.",
        next_recommended_action=next_action(status, health, targets_checked),
    )


def load_monitor_cycle_payload(path_value: str, *, reports_dir: Path) -> dict[str, Any]:
    path = Path(path_value) if path_value else latest_monitor_cycle_json_path(reports_dir)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    raw = payload.get("monitor_cycle", payload)
    return raw if isinstance(raw, dict) else {}


def infer_execution_mode(status: object, active_status: object) -> str:
    if status is None:
        return "UNKNOWN_NO_AUTOPILOT_RUN_RECORDED"
    if getattr(status, "state", "") == "RUNNING":
        return "RUNNING_NOW"
    if active_status is not None and getattr(active_status, "state", "") == "RUNNING":
        return "ACTIVE_MONITOR_LOOP_RUNNING"
    return "ON_DEMAND_CLI_OR_DASHBOARD_RUN"


def next_action(status: object, health: EvidenceHealthReport, targets_checked: int) -> str:
    if status is None:
        return "Run Evidence Autopilot once and confirm it writes status, evidence health, and daily brief artifacts."
    if getattr(status, "state", "") == "FAILED":
        return "Open the autopilot status and fix the recorded failure before trusting evidence collection."
    if targets_checked == 0:
        return "Add or verify monitor targets; the latest autopilot run did not check any symbols."
    if health.pending_alerts:
        return "Run the alert outcome updater when post-alert minute bars are available."
    if health.unscorable_alerts:
        return "Review unscorable alerts as data-quality loss; do not treat them as pending or completed evidence."
    if health.completed_alerts < health.evidence_gate.required_alerts:
        return "Keep collecting evidence; optimization remains locked until completed-alert thresholds are met."
    return "Evidence collection is usable for review; keep strategy changes gated by sample-size discipline."


def export_evidence_autopilot_reliability_report(
    report: EvidenceAutopilotReliabilityReport,
    *,
    json_path: Path = EVIDENCE_AUTOPILOT_LATEST_JSON,
    markdown_path: Path = EVIDENCE_AUTOPILOT_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVIDENCE_AUTOPILOT_RELIABILITY_SCHEMA_VERSION,
        "engine_version": EVIDENCE_AUTOPILOT_RELIABILITY_VERSION,
        "report": asdict(report),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_evidence_autopilot_markdown(report), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def load_latest_evidence_autopilot_reliability_report(
    path: Path = EVIDENCE_AUTOPILOT_LATEST_JSON,
) -> EvidenceAutopilotReliabilityReport | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw = payload.get("report", payload)
    if not isinstance(raw, dict):
        return None
    return EvidenceAutopilotReliabilityReport(
        generated_at=str(raw.get("generated_at", "")),
        autopilot_status_path=str(raw.get("autopilot_status_path", "")),
        latest_run_state=str(raw.get("latest_run_state", "")),
        latest_run_started_at=str(raw.get("latest_run_started_at", "")),
        latest_run_completed_at=str(raw.get("latest_run_completed_at", "")),
        latest_run_duration_seconds=parse_optional_float(raw.get("latest_run_duration_seconds")),
        execution_mode=str(raw.get("execution_mode", "")),
        monitor_cycle_completed=bool(raw.get("monitor_cycle_completed", False)),
        outcome_update_completed=bool(raw.get("outcome_update_completed", False)),
        evidence_report_generated=bool(raw.get("evidence_report_generated", False)),
        daily_brief_generated=bool(raw.get("daily_brief_generated", False)),
        monitor_cycle_path=str(raw.get("monitor_cycle_path", "")),
        outcome_status_path=str(raw.get("outcome_status_path", "")),
        evidence_report_path=str(raw.get("evidence_report_path", "")),
        daily_brief_path=str(raw.get("daily_brief_path", "")),
        targets_checked=parse_int(raw.get("targets_checked")),
        alerts_added=parse_int(raw.get("alerts_added")),
        active_alerts=parse_int(raw.get("active_alerts")),
        tracked_alerts=parse_int(raw.get("tracked_alerts")),
        outcomes_updated=parse_int(raw.get("outcomes_updated")),
        completed_alerts=parse_int(raw.get("completed_alerts")),
        pending_alerts=parse_int(raw.get("pending_alerts")),
        unscorable_alerts=parse_int(raw.get("unscorable_alerts")),
        stale_pending_alerts=parse_int(raw.get("stale_pending_alerts")),
        missing_minute_bar_alerts=parse_int(raw.get("missing_minute_bar_alerts")),
        missing_outcome_alerts=parse_int(raw.get("missing_outcome_alerts")),
        warnings=[str(item) for item in raw.get("warnings", [])] if isinstance(raw.get("warnings"), list) else [],
        failure_reason=str(raw.get("failure_reason", "")),
        next_recommended_action=str(raw.get("next_recommended_action", "")),
    )


def format_evidence_autopilot_markdown(report: EvidenceAutopilotReliabilityReport) -> str:
    lines = [
        f"# Momentum Hunter Evidence Autopilot Reliability - {report.generated_at}",
        "",
        "Read-only reliability report. This does not change alert generation, scoring, readiness, or trade planning.",
        "",
        "## Status",
        "",
        f"- State: {report.latest_run_state}",
        f"- Execution mode: {report.execution_mode}",
        f"- Started: {report.latest_run_started_at or 'n/a'}",
        f"- Completed: {report.latest_run_completed_at or 'n/a'}",
        f"- Duration seconds: {fmt(report.latest_run_duration_seconds)}",
        "",
        "## Pipeline",
        "",
        f"- Monitor cycle completed: {yes_no(report.monitor_cycle_completed)}",
        f"- Outcome updater completed: {yes_no(report.outcome_update_completed)}",
        f"- Evidence health generated: {yes_no(report.evidence_report_generated)}",
        f"- Daily brief generated: {yes_no(report.daily_brief_generated)}",
        "",
        "## Evidence Counts",
        "",
        f"- Targets checked: {report.targets_checked}",
        f"- Alerts added: {report.alerts_added}",
        f"- Active alerts: {report.active_alerts}",
        f"- Tracked alerts: {report.tracked_alerts}",
        f"- Outcomes updated: {report.outcomes_updated}",
        f"- Completed alerts: {report.completed_alerts}",
        f"- Pending alerts: {report.pending_alerts}",
        f"- Unscorable alerts: {report.unscorable_alerts}",
        f"- Stale pending alerts: {report.stale_pending_alerts}",
        f"- Missing minute-bar alerts: {report.missing_minute_bar_alerts}",
        f"- Missing outcome alerts: {report.missing_outcome_alerts}",
        "",
        "## Artifacts",
        "",
        f"- Monitor cycle: `{report.monitor_cycle_path or 'none'}`",
        f"- Outcome status: `{report.outcome_status_path or 'none'}`",
        f"- Evidence report: `{report.evidence_report_path or 'none'}`",
        f"- Daily brief: `{report.daily_brief_path or 'none'}`",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] if report.warnings else ["- None."])
    lines.extend(["", "## Next Recommended Action", "", report.next_recommended_action or "No action determined.", ""])
    return "\n".join(lines)


def run_duration_seconds(started_at: str, completed_at: str) -> float | None:
    start = parse_datetime(started_at)
    end = parse_datetime(completed_at)
    if not start or not end:
        return None
    return round((end - start).total_seconds(), 3)


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_optional_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def fmt(value: object) -> str:
    number = parse_optional_float(value)
    return "n/a" if number is None else f"{number:.3f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter Evidence Autopilot latest reports.")
    parser.add_argument("--json", type=Path, default=EVIDENCE_AUTOPILOT_LATEST_JSON)
    parser.add_argument("--md", type=Path, default=EVIDENCE_AUTOPILOT_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_evidence_autopilot_reliability_report()
    paths = export_evidence_autopilot_reliability_report(report, json_path=args.json, markdown_path=args.md)
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
