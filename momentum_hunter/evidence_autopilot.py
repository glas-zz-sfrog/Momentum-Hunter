from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from momentum_hunter.active_monitor import (
    ACTIVE_MONITOR_STATUS_PATH,
    MonitorCycleReport,
    latest_monitor_cycle_json_path,
    run_monitor_cycle,
)
from momentum_hunter.alert_outcome_updater import (
    ALERT_OUTCOME_UPDATE_STATUS_PATH,
    AlertOutcomeUpdateReport,
    update_alert_store_from_minute_bars,
)
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.evidence_health import (
    EvidenceHealthReport,
    build_evidence_health_report,
    export_evidence_health_report,
    format_reason_counts,
)
from momentum_hunter.time_utils import now_central


EVIDENCE_AUTOPILOT_SCHEMA_VERSION = 1
EVIDENCE_AUTOPILOT_VERSION = "evidence_autopilot_v1"
EVIDENCE_AUTOPILOT_STATUS_PATH = DATA_DIR / "evidence-autopilot-status.json"


@dataclass(frozen=True)
class EvidenceAutopilotStatus:
    state: str
    started_at: str
    updated_at: str
    completed_at: str = ""
    monitor_cycle_completed: bool = False
    outcome_update_completed: bool = False
    evidence_report_generated: bool = False
    daily_brief_generated: bool = False
    monitor_cycle_path: str = ""
    outcome_status_path: str = ""
    evidence_report_path: str = ""
    daily_brief_path: str = ""
    new_alert_count: int = 0
    active_alert_count: int = 0
    tracked_alert_count: int = 0
    updated_outcome_count: int = 0
    completed_outcome_count: int = 0
    pending_alert_count: int = 0
    unscorable_alert_count: int = 0
    stale_pending_alert_count: int = 0
    warning_count: int = 0
    warnings: list[str] = field(default_factory=list)
    last_error: str = ""


def run_evidence_autopilot(
    *,
    output_dir: Path | None = None,
    status_path: Path = EVIDENCE_AUTOPILOT_STATUS_PATH,
    fetch_missing_market_data: bool = True,
    refresh_target_market_data: bool = True,
    fetch_missing_bars: bool = True,
    monitor_cycle_runner: Callable[..., MonitorCycleReport] = run_monitor_cycle,
    outcome_updater: Callable[..., AlertOutcomeUpdateReport] = update_alert_store_from_minute_bars,
    evidence_builder: Callable[..., EvidenceHealthReport] = build_evidence_health_report,
) -> EvidenceAutopilotStatus:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    started = now_central()
    running = EvidenceAutopilotStatus(
        state="RUNNING",
        started_at=started.isoformat(),
        updated_at=started.isoformat(),
        warnings=[],
    )
    save_evidence_autopilot_status(running, status_path)
    try:
        monitor_report = monitor_cycle_runner(
            output_dir=output_dir,
            fetch_missing_market_data=fetch_missing_market_data,
            refresh_target_market_data=refresh_target_market_data,
            status_path=ACTIVE_MONITOR_STATUS_PATH,
        )
        monitor_path = latest_monitor_cycle_json_path(output_dir)
        outcome_report = outcome_updater(
            fetch_missing_bars=fetch_missing_bars,
            status_path=ALERT_OUTCOME_UPDATE_STATUS_PATH,
        )
        evidence_report = evidence_builder()
        evidence_paths = export_evidence_health_report(evidence_report, output_dir)
        brief_path = write_daily_evidence_brief(
            monitor_report=monitor_report,
            outcome_report=outcome_report,
            evidence_report=evidence_report,
            output_dir=output_dir,
        )
        completed = now_central()
        warnings = dedupe(list(monitor_report.warnings) + list(outcome_report.warnings) + list(evidence_report.warnings))
        status = EvidenceAutopilotStatus(
            state="COMPLETED",
            started_at=started.isoformat(),
            updated_at=completed.isoformat(),
            completed_at=completed.isoformat(),
            monitor_cycle_completed=True,
            outcome_update_completed=True,
            evidence_report_generated=True,
            daily_brief_generated=True,
            monitor_cycle_path=str(monitor_path or ""),
            outcome_status_path=str(ALERT_OUTCOME_UPDATE_STATUS_PATH),
            evidence_report_path=str(evidence_paths.get("evidence_report", "")),
            daily_brief_path=str(brief_path),
            new_alert_count=monitor_report.new_alert_count,
            active_alert_count=monitor_report.active_alert_count,
            tracked_alert_count=monitor_report.tracked_alert_count,
            updated_outcome_count=outcome_report.updated_alert_count,
            completed_outcome_count=outcome_report.completed_alert_count,
            pending_alert_count=evidence_report.pending_alerts,
            unscorable_alert_count=evidence_report.unscorable_alerts,
            stale_pending_alert_count=len(evidence_report.stale_pending_alerts),
            warning_count=len(warnings),
            warnings=warnings,
        )
        save_evidence_autopilot_status(status, status_path)
        return status
    except Exception as exc:
        failed = now_central()
        status = EvidenceAutopilotStatus(
            state="FAILED",
            started_at=started.isoformat(),
            updated_at=failed.isoformat(),
            completed_at=failed.isoformat(),
            warnings=[],
            last_error=f"{type(exc).__name__}: {exc}",
        )
        save_evidence_autopilot_status(status, status_path)
        raise


def write_daily_evidence_brief(
    *,
    monitor_report: MonitorCycleReport,
    outcome_report: AlertOutcomeUpdateReport,
    evidence_report: EvidenceHealthReport,
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = now_central()
    path = output_dir / f"daily-evidence-brief-{generated.date().isoformat()}.md"
    gate = evidence_report.evidence_gate
    lines = [
        f"# Momentum Hunter Daily Evidence Brief - {generated.date().isoformat()}",
        "",
        "Evidence-collection brief only. This does not change trading logic, scoring, readiness, ranking, or trade-planning rules.",
        "",
        "## Evidence Status",
        "",
        f"- Evidence status: {gate.evidence_status}",
        f"- Completed alerts: {evidence_report.completed_alerts} / {gate.required_alerts}",
        f"- Strategy optimization: {gate.strategy_optimization_status}",
        f"- Allowed action: {gate.allowed_action}",
        "",
        "## Today's Evidence Loop",
        "",
        f"- Monitor cycle completed: yes",
        f"- Targets monitored: {monitor_report.target_count}",
        f"- New alerts: {monitor_report.new_alert_count}",
        f"- Active alerts: {monitor_report.active_alert_count}",
        f"- Tracked alerts: {monitor_report.tracked_alert_count}",
        f"- Outcome updates changed: {outcome_report.updated_alert_count}",
        f"- Completed outcomes: {outcome_report.completed_alert_count}",
        f"- Pending alerts: {evidence_report.pending_alerts}",
        f"- Unscorable alerts: {evidence_report.unscorable_alerts}",
        "",
        "## Data Quality",
        "",
        f"- Stale pending alerts: {len(evidence_report.stale_pending_alerts)}",
        f"- Unscorable alerts: {evidence_report.unscorable_alerts}",
        f"- Unscorable reasons: {format_reason_counts(evidence_report.unscorable_by_reason)}",
        f"- Missing minute-bar alerts: {len(evidence_report.missing_minute_bar_alerts)}",
        f"- Missing outcome alerts: {len(evidence_report.missing_outcome_alerts)}",
        f"- Incomplete outcome alerts: {len(evidence_report.incomplete_outcome_alerts)}",
        "",
        "## What This Means",
        "",
        daily_meaning(evidence_report),
        "",
        "## Warnings",
        "",
    ]
    warnings = dedupe(list(monitor_report.warnings) + list(outcome_report.warnings) + list(evidence_report.warnings))
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def daily_meaning(report: EvidenceHealthReport) -> str:
    gate = report.evidence_gate
    if gate.strategy_optimization_status == "LOCKED":
        return (
            "Momentum Hunter is still collecting evidence. Use this information to monitor reliability "
            "and unresolved alerts, not to change strategy rules."
        )
    return "Evidence thresholds are met for review, but any strategy changes should still be evaluated deliberately."


def save_evidence_autopilot_status(
    status: EvidenceAutopilotStatus,
    path: Path = EVIDENCE_AUTOPILOT_STATUS_PATH,
) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": EVIDENCE_AUTOPILOT_SCHEMA_VERSION,
        "engine_version": EVIDENCE_AUTOPILOT_VERSION,
        "status": asdict(status),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_evidence_autopilot_status(path: Path = EVIDENCE_AUTOPILOT_STATUS_PATH) -> EvidenceAutopilotStatus | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw = payload.get("status", payload)
    if not isinstance(raw, dict):
        return None
    return EvidenceAutopilotStatus(
        state=str(raw.get("state", "")),
        started_at=str(raw.get("started_at", "")),
        updated_at=str(raw.get("updated_at", "")),
        completed_at=str(raw.get("completed_at", "")),
        monitor_cycle_completed=bool(raw.get("monitor_cycle_completed", False)),
        outcome_update_completed=bool(raw.get("outcome_update_completed", False)),
        evidence_report_generated=bool(raw.get("evidence_report_generated", False)),
        daily_brief_generated=bool(raw.get("daily_brief_generated", False)),
        monitor_cycle_path=str(raw.get("monitor_cycle_path", "")),
        outcome_status_path=str(raw.get("outcome_status_path", "")),
        evidence_report_path=str(raw.get("evidence_report_path", "")),
        daily_brief_path=str(raw.get("daily_brief_path", "")),
        new_alert_count=parse_int(raw.get("new_alert_count")),
        active_alert_count=parse_int(raw.get("active_alert_count")),
        tracked_alert_count=parse_int(raw.get("tracked_alert_count")),
        updated_outcome_count=parse_int(raw.get("updated_outcome_count")),
        completed_outcome_count=parse_int(raw.get("completed_outcome_count")),
        pending_alert_count=parse_int(raw.get("pending_alert_count")),
        unscorable_alert_count=parse_int(raw.get("unscorable_alert_count")),
        stale_pending_alert_count=parse_int(raw.get("stale_pending_alert_count")),
        warning_count=parse_int(raw.get("warning_count")),
        warnings=[str(item) for item in raw.get("warnings", [])] if isinstance(raw.get("warnings"), list) else [],
        last_error=str(raw.get("last_error", "")),
    )


def parse_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Momentum Hunter Evidence Autopilot once.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--status-path", type=Path, default=EVIDENCE_AUTOPILOT_STATUS_PATH)
    parser.add_argument("--no-fetch-missing-market-data", action="store_true")
    parser.add_argument("--no-refresh-target-market-data", action="store_true")
    parser.add_argument("--no-fetch-missing-bars", action="store_true")
    args = parser.parse_args(argv)
    status = run_evidence_autopilot(
        output_dir=args.output_dir,
        status_path=args.status_path,
        fetch_missing_market_data=not args.no_fetch_missing_market_data,
        refresh_target_market_data=not args.no_refresh_target_market_data,
        fetch_missing_bars=not args.no_fetch_missing_bars,
    )
    print(json.dumps(asdict(status), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
