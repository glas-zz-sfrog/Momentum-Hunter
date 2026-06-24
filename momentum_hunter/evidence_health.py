from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.alert_outcome_updater import ALERT_OUTCOME_UPDATE_STATUS_PATH, OPPORTUNITY_MINUTE_BARS_PATH, load_update_report
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OpportunityAlert,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
    parse_datetime,
    safe_stamp,
)
from momentum_hunter.time_utils import now_central


EVIDENCE_HEALTH_SCHEMA_VERSION = 1
EVIDENCE_HEALTH_ENGINE_VERSION = "evidence_health_v1"
DEFAULT_STALE_PENDING_HOURS = 24


@dataclass(frozen=True)
class AlertIssue:
    alert_id: str
    symbol: str
    alert_type: str
    timestamp: str
    issue: str
    detail: str


@dataclass(frozen=True)
class EvidenceGate:
    completed_alerts: int
    required_alerts: int
    evidence_status: str
    allowed_action: str
    strategy_optimization_status: str
    reason: str


@dataclass(frozen=True)
class EvidenceHealthReport:
    generated_at: str
    source_alerts_path: str
    source_minute_bars_path: str
    source_outcome_status_path: str
    total_alerts: int
    completed_alerts: int
    pending_alerts: int
    unscorable_alerts: int
    success_count: int
    failure_count: int
    noise_count: int
    late_count: int
    completion_rate_pct: float | None
    alerts_generated: int
    alerts_captured: int
    alerts_classified: int
    completed_outcomes: int
    stale_pending_alerts: list[AlertIssue]
    unscorable_alert_issues: list[AlertIssue]
    unscorable_by_reason: dict[str, int]
    missing_minute_bar_alerts: list[AlertIssue]
    missing_outcome_alerts: list[AlertIssue]
    incomplete_outcome_alerts: list[AlertIssue]
    missing_readiness_state_alerts: list[AlertIssue]
    missing_news_snapshot_alerts: list[AlertIssue]
    monitor_started: bool
    monitor_completed: bool
    alerts_written: bool
    outcome_jobs_executed: bool
    outcome_classifications_saved: bool
    evidence_gate: EvidenceGate
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReliabilityReport:
    generated_at: str
    window_days: int
    monitor_cycle_count: int
    successful_cycle_count: int
    failed_cycle_count: int
    cycle_reliability_pct: float | None
    warning_cycle_count: int
    alerts_generated: int
    alerts_completed: int
    alert_completion_rate_pct: float | None
    outcome_job_executed: bool
    outcome_processing_success_rate_pct: float | None
    missing_data_incident_count: int
    latest_monitor_cycle_at: str
    latest_outcome_update_at: str
    warnings: list[str] = field(default_factory=list)


def build_evidence_health_report(
    *,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    outcome_status_path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH,
    reports_dir: Path | None = None,
    generated_at: datetime | None = None,
    stale_pending_hours: int = DEFAULT_STALE_PENDING_HOURS,
) -> EvidenceHealthReport:
    generated_at = generated_at or now_central()
    reports_dir = reports_dir or DATA_DIR / "reports"
    alerts = load_alerts(alerts_path)
    minute_bar_symbols = load_minute_bar_symbols(minute_bars_path)
    completed = [alert for alert in alerts if is_completed_alert(alert)]
    unscorable = [alert for alert in alerts if is_unscorable_alert(alert)]
    pending = [alert for alert in alerts if is_pending_alert(alert)]
    stale_cutoff = generated_at - timedelta(hours=stale_pending_hours)
    stale_pending = [
        issue_for(alert, "STALE_PENDING_ALERT", f"Pending longer than {stale_pending_hours} hour(s).")
        for alert in pending
        if alert_timestamp_before(alert, stale_cutoff)
    ]
    unscorable_issues = [
        issue_for(alert, alert.outcome.classification, "; ".join(alert.outcome.evaluation_notes) or "Terminal data-quality outcome.")
        for alert in unscorable
    ]
    unscorable_by_reason = reason_counts(unscorable)
    missing_bars = [
        issue_for(alert, "MISSING_MINUTE_BARS", "No minute bars are stored for this alert symbol.")
        for alert in pending
        if alert.price is not None and alert.symbol and alert.symbol not in minute_bar_symbols
    ]
    missing_outcomes = [
        issue_for(alert, "MISSING_OUTCOME_DATA", "; ".join(alert.outcome.evaluation_notes) or "Outcome is pending.")
        for alert in pending
    ]
    incomplete_outcomes = [
        issue_for(alert, "INCOMPLETE_OUTCOME_CALCULATION", "Completed alert is missing one or more required return/MFE/MAE values.")
        for alert in completed
        if has_incomplete_outcome(alert)
    ]
    missing_readiness = [
        issue_for(alert, "MISSING_READINESS_STATE", "Alert current_state is empty.")
        for alert in alerts
        if not alert.current_state
    ]
    missing_news = [
        issue_for(alert, "MISSING_NEWS_SNAPSHOT", "Alert news_catalyst is empty.")
        for alert in alerts
        if not alert.news_catalyst
    ]
    outcome_status = load_update_report(outcome_status_path)
    monitor_status = load_json(DATA_DIR / "active-monitor-status.json")
    monitor_cycles = load_monitor_cycle_payloads(reports_dir)
    warnings = build_evidence_warnings(
        total_alerts=len(alerts),
        stale_pending=stale_pending,
        missing_bars=missing_bars,
        missing_outcomes=missing_outcomes,
        incomplete_outcomes=incomplete_outcomes,
        unscorable_alerts=unscorable_issues,
        missing_readiness=missing_readiness,
        missing_news=missing_news,
        completed_count=len(completed),
    )
    return EvidenceHealthReport(
        generated_at=generated_at.isoformat(),
        source_alerts_path=str(alerts_path),
        source_minute_bars_path=str(minute_bars_path),
        source_outcome_status_path=str(outcome_status_path),
        total_alerts=len(alerts),
        completed_alerts=len(completed),
        pending_alerts=len(pending),
        unscorable_alerts=len(unscorable),
        success_count=classification_count(completed, "SUCCESSFUL"),
        failure_count=classification_count(completed, "FAILED"),
        noise_count=classification_count(completed, "NOISE"),
        late_count=classification_count(completed, "LATE"),
        completion_rate_pct=percent(len(completed), len(completed) + len(pending)),
        alerts_generated=len(alerts),
        alerts_captured=count_captured_alerts(alerts),
        alerts_classified=len(completed),
        completed_outcomes=len(completed),
        stale_pending_alerts=stale_pending,
        unscorable_alert_issues=unscorable_issues,
        unscorable_by_reason=unscorable_by_reason,
        missing_minute_bar_alerts=missing_bars,
        missing_outcome_alerts=missing_outcomes,
        incomplete_outcome_alerts=incomplete_outcomes,
        missing_readiness_state_alerts=missing_readiness,
        missing_news_snapshot_alerts=missing_news,
        monitor_started=bool(monitor_status or monitor_cycles),
        monitor_completed=bool(monitor_cycles),
        alerts_written=alerts_path.exists() and len(alerts) > 0,
        outcome_jobs_executed=outcome_status is not None,
        outcome_classifications_saved=len(completed) > 0,
        evidence_gate=evidence_gate(len(completed)),
        warnings=warnings,
    )


def build_reliability_report(
    *,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    outcome_status_path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH,
    reports_dir: Path | None = None,
    generated_at: datetime | None = None,
    window_days: int = 7,
) -> ReliabilityReport:
    generated_at = generated_at or now_central()
    reports_dir = reports_dir or DATA_DIR / "reports"
    since = generated_at - timedelta(days=window_days)
    cycles = [
        cycle
        for cycle in load_monitor_cycle_payloads(reports_dir)
        if (parsed := parse_datetime(str(cycle.get("generated_at", "")))) is not None and parsed >= since
    ]
    status = load_json(DATA_DIR / "active-monitor-status.json")
    failed_cycles = 1 if isinstance(status, dict) and status.get("state") == "FAILED" else 0
    successful_cycles = len(cycles)
    warning_cycles = sum(1 for cycle in cycles if isinstance(cycle.get("warnings"), list) and cycle.get("warnings"))
    alerts = load_alerts(alerts_path)
    completed = [alert for alert in alerts if is_completed_alert(alert)]
    pending = [alert for alert in alerts if is_pending_alert(alert)]
    outcome_status = load_update_report(outcome_status_path)
    outcome_success_rate = (
        percent(outcome_status.completed_alert_count, outcome_status.completed_alert_count + outcome_status.pending_alert_count)
        if outcome_status
        else None
    )
    missing_incidents = count_missing_data_incidents(cycles, alerts, outcome_status)
    warnings = []
    if not cycles:
        warnings.append("NO_MONITOR_CYCLES_IN_WINDOW")
    if failed_cycles:
        warnings.append("ACTIVE_MONITOR_STATUS_FAILED")
    if outcome_status is None:
        warnings.append("NO_OUTCOME_JOB_STATUS_FOUND")
    return ReliabilityReport(
        generated_at=generated_at.isoformat(),
        window_days=window_days,
        monitor_cycle_count=len(cycles),
        successful_cycle_count=successful_cycles,
        failed_cycle_count=failed_cycles,
        cycle_reliability_pct=percent(successful_cycles, successful_cycles + failed_cycles),
        warning_cycle_count=warning_cycles,
        alerts_generated=len(alerts),
        alerts_completed=len(completed),
        alert_completion_rate_pct=percent(len(completed), len(completed) + len(pending)),
        outcome_job_executed=outcome_status is not None,
        outcome_processing_success_rate_pct=outcome_success_rate,
        missing_data_incident_count=missing_incidents,
        latest_monitor_cycle_at=max([str(cycle.get("generated_at", "")) for cycle in cycles], default=""),
        latest_outcome_update_at=outcome_status.generated_at if outcome_status else "",
        warnings=warnings,
    )


def export_evidence_reports(
    health: EvidenceHealthReport,
    reliability: ReliabilityReport,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    paths = {}
    paths.update(export_evidence_health_report(health, output_dir))
    paths.update(export_reliability_report(reliability, output_dir))
    return paths


def export_evidence_health_report(health: EvidenceHealthReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    health_base = f"evidence-health-report-{safe_stamp(health.generated_at)}"
    paths = {
        "evidence_json": output_dir / f"{health_base}.json",
        "evidence_report": output_dir / f"{health_base}.md",
    }
    write_json_report(health, paths["evidence_json"])
    write_evidence_markdown(health, paths["evidence_report"])
    return paths


def export_reliability_report(reliability: ReliabilityReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    reliability_base = f"reliability-report-{safe_stamp(reliability.generated_at)}"
    paths = {
        "reliability_json": output_dir / f"{reliability_base}.json",
        "reliability_report": output_dir / f"{reliability_base}.md",
    }
    write_json_report(reliability, paths["reliability_json"])
    write_reliability_markdown(reliability, paths["reliability_report"])
    return paths


def write_json_report(report: EvidenceHealthReport | ReliabilityReport, path: Path) -> None:
    payload = {
        "schema_version": EVIDENCE_HEALTH_SCHEMA_VERSION,
        "engine_version": EVIDENCE_HEALTH_ENGINE_VERSION,
        "report": asdict(report),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_evidence_markdown(report: EvidenceHealthReport, path: Path) -> None:
    gate = report.evidence_gate
    lines = [
        f"# Momentum Hunter Evidence Health - {report.generated_at}",
        "",
        "Evidence-collection report only. This does not change signal generation, scoring, readiness, ranking, or trade-planning logic.",
        "",
        "## Evidence Status",
        "",
        f"- Evidence status: {gate.evidence_status}",
        f"- Completed alerts: {report.completed_alerts} / {gate.required_alerts} required",
        f"- Allowed action: {gate.allowed_action}",
        f"- Strategy optimization: {gate.strategy_optimization_status}",
        f"- Reason: {gate.reason}",
        "",
        "## Alert Funnel",
        "",
        f"- Alerts generated: {report.alerts_generated}",
        f"- Alerts captured: {report.alerts_captured}",
        f"- Alerts classified: {report.alerts_classified}",
        f"- Completed outcomes: {report.completed_outcomes}",
        f"- Scorable completion rate: {format_pct(report.completion_rate_pct)}",
        "",
        "## Outcome Breakdown",
        "",
        f"- Successful: {report.success_count}",
        f"- Failed: {report.failure_count}",
        f"- Noise: {report.noise_count}",
        f"- Late: {report.late_count}",
        f"- Pending: {report.pending_alerts}",
        f"- Unscorable: {report.unscorable_alerts}",
        "",
        "## Data Quality",
        "",
        f"- Stale pending alerts: {len(report.stale_pending_alerts)}",
        f"- Unscorable alerts: {report.unscorable_alerts}",
        f"- Missing minute-bar alerts: {len(report.missing_minute_bar_alerts)}",
        f"- Missing outcome alerts: {len(report.missing_outcome_alerts)}",
        f"- Incomplete outcome alerts: {len(report.incomplete_outcome_alerts)}",
        f"- Missing readiness states: {len(report.missing_readiness_state_alerts)}",
        f"- Missing news snapshots: {len(report.missing_news_snapshot_alerts)}",
        f"- Unscorable reasons: {format_reason_counts(report.unscorable_by_reason)}",
        "",
        "## Pipeline Checks",
        "",
        f"- Monitor started: {format_bool(report.monitor_started)}",
        f"- Monitor completed: {format_bool(report.monitor_completed)}",
        f"- Alerts written: {format_bool(report.alerts_written)}",
        f"- Outcome jobs executed: {format_bool(report.outcome_jobs_executed)}",
        f"- Outcome classifications saved: {format_bool(report.outcome_classifications_saved)}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] if report.warnings else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reliability_markdown(report: ReliabilityReport, path: Path) -> None:
    lines = [
        f"# Momentum Hunter Reliability - {report.generated_at}",
        "",
        "Weekly-style reliability report for evidence collection infrastructure.",
        "",
        f"- Window: {report.window_days} day(s)",
        f"- Monitor cycles: {report.monitor_cycle_count}",
        f"- Successful cycles: {report.successful_cycle_count}",
        f"- Failed cycles: {report.failed_cycle_count}",
        f"- Cycle reliability: {format_pct(report.cycle_reliability_pct)}",
        f"- Cycles with warnings: {report.warning_cycle_count}",
        f"- Alerts generated: {report.alerts_generated}",
        f"- Alerts completed: {report.alerts_completed}",
        f"- Alert completion rate: {format_pct(report.alert_completion_rate_pct)}",
        f"- Outcome job executed: {format_bool(report.outcome_job_executed)}",
        f"- Outcome processing success rate: {format_pct(report.outcome_processing_success_rate_pct)}",
        f"- Missing data incidents: {report.missing_data_incident_count}",
        f"- Latest monitor cycle: {report.latest_monitor_cycle_at or 'n/a'}",
        f"- Latest outcome update: {report.latest_outcome_update_at or 'n/a'}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] if report.warnings else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def evidence_gate(completed_alerts: int) -> EvidenceGate:
    if completed_alerts < 25:
        return EvidenceGate(
            completed_alerts=completed_alerts,
            required_alerts=25,
            evidence_status="COLLECTING",
            allowed_action="Collect evidence only",
            strategy_optimization_status="LOCKED",
            reason=f"{completed_alerts} completed alert(s); minimum 25 required to identify patterns.",
        )
    if completed_alerts < 50:
        return EvidenceGate(
            completed_alerts=completed_alerts,
            required_alerts=50,
            evidence_status="EARLY_PATTERNS",
            allowed_action="Identify patterns",
            strategy_optimization_status="LOCKED",
            reason=f"{completed_alerts} completed alert(s); minimum 50 required before recommending investigations.",
        )
    if completed_alerts < 100:
        return EvidenceGate(
            completed_alerts=completed_alerts,
            required_alerts=100,
            evidence_status="INVESTIGATION_READY",
            allowed_action="Recommend investigations",
            strategy_optimization_status="LOCKED",
            reason=f"{completed_alerts} completed alert(s); minimum 100 required before strategy modifications.",
        )
    return EvidenceGate(
        completed_alerts=completed_alerts,
        required_alerts=100,
        evidence_status="STRATEGY_REVIEW_READY",
        allowed_action="Recommend strategy modifications",
        strategy_optimization_status="UNLOCKED_FOR_REVIEW",
        reason=f"{completed_alerts} completed alert(s); evidence threshold met for strategy-modification review.",
    )


def load_monitor_cycle_payloads(reports_dir: Path) -> list[dict[str, object]]:
    if not reports_dir.exists():
        return []
    cycles = []
    for path in reports_dir.glob("active-monitor-cycle-*.json"):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        cycle = payload.get("monitor_cycle")
        if isinstance(cycle, dict):
            cycles.append(cycle)
    return cycles


def load_minute_bar_symbols(path: Path) -> set[str]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        return set()
    bars = payload.get("bars")
    if not isinstance(bars, dict):
        return set()
    return {str(symbol).upper() for symbol, rows in bars.items() if isinstance(rows, list) and rows}


def load_json(path: Path) -> object:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def count_captured_alerts(alerts: list[OpportunityAlert]) -> int:
    return sum(1 for alert in alerts if alert.alert_id and alert.timestamp and alert.symbol)


def has_incomplete_outcome(alert: OpportunityAlert) -> bool:
    outcome = alert.outcome
    required = [
        outcome.five_minute_return_pct,
        outcome.fifteen_minute_return_pct,
        outcome.thirty_minute_return_pct,
        outcome.sixty_minute_return_pct,
        outcome.mfe_60m_pct,
        outcome.mae_60m_pct,
    ]
    return any(value is None for value in required)


def alert_timestamp_before(alert: OpportunityAlert, cutoff: datetime) -> bool:
    parsed = parse_datetime(alert.timestamp)
    if parsed is None:
        return False
    return parsed < cutoff


def issue_for(alert: OpportunityAlert, issue: str, detail: str) -> AlertIssue:
    return AlertIssue(
        alert_id=alert.alert_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type,
        timestamp=alert.timestamp,
        issue=issue,
        detail=detail,
    )


def classification_count(alerts: list[OpportunityAlert], classification: str) -> int:
    return sum(1 for alert in alerts if alert.outcome.classification == classification)


def reason_counts(alerts: list[OpportunityAlert]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for alert in alerts:
        reason = alert.outcome.classification or "UNSCORABLE_INCOMPLETE_EVIDENCE"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def count_missing_data_incidents(cycles: list[dict[str, object]], alerts: list[OpportunityAlert], outcome_status) -> int:
    cycle_incidents = 0
    for cycle in cycles:
        warnings = cycle.get("warnings")
        if isinstance(warnings, list):
            cycle_incidents += sum(1 for warning in warnings if "MISSING" in str(warning) or "WITHOUT" in str(warning))
        cycle_incidents += len(cycle.get("uncovered_missing_symbols", [])) if isinstance(cycle.get("uncovered_missing_symbols"), list) else 0
    pending_incidents = sum(1 for alert in alerts if is_pending_alert(alert) or is_unscorable_alert(alert))
    outcome_incidents = len(outcome_status.warnings) if outcome_status else 0
    return cycle_incidents + pending_incidents + outcome_incidents


def build_evidence_warnings(
    *,
    total_alerts: int,
    stale_pending: list[AlertIssue],
    missing_bars: list[AlertIssue],
    missing_outcomes: list[AlertIssue],
    incomplete_outcomes: list[AlertIssue],
    unscorable_alerts: list[AlertIssue],
    missing_readiness: list[AlertIssue],
    missing_news: list[AlertIssue],
    completed_count: int,
) -> list[str]:
    warnings: list[str] = []
    if total_alerts == 0:
        warnings.append("NO_ALERTS_RECORDED")
    if completed_count < 25:
        warnings.append("EVIDENCE_THRESHOLD_LOCKED: completed alerts below 25")
    if stale_pending:
        warnings.append(f"STALE_PENDING_ALERTS:{len(stale_pending)}")
    if missing_bars:
        warnings.append(f"MISSING_MINUTE_BARS:{len(missing_bars)}")
    if missing_outcomes:
        warnings.append(f"MISSING_OUTCOME_DATA:{len(missing_outcomes)}")
    if incomplete_outcomes:
        warnings.append(f"INCOMPLETE_OUTCOME_CALCULATIONS:{len(incomplete_outcomes)}")
    if unscorable_alerts:
        warnings.append(f"UNSCORABLE_ALERTS:{len(unscorable_alerts)}")
    if missing_readiness:
        warnings.append(f"MISSING_READINESS_STATES:{len(missing_readiness)}")
    if missing_news:
        warnings.append(f"MISSING_NEWS_SNAPSHOTS:{len(missing_news)}")
    return warnings


def percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value}%"


def format_bool(value: bool) -> str:
    return "yes" if value else "no"


def format_reason_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{reason}:{count}" for reason, count in counts.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter evidence health and reliability reports.")
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--minute-bars-path", type=Path, default=OPPORTUNITY_MINUTE_BARS_PATH)
    parser.add_argument("--outcome-status-path", type=Path, default=ALERT_OUTCOME_UPDATE_STATUS_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DATA_DIR / "reports")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--stale-pending-hours", type=int, default=DEFAULT_STALE_PENDING_HOURS)
    parser.add_argument("--report-kind", choices=["evidence", "reliability", "both"], default="both")
    args = parser.parse_args(argv)
    generated_at = now_central()
    paths: dict[str, Path] = {}
    if args.report_kind in {"evidence", "both"}:
        health = build_evidence_health_report(
            alerts_path=args.alerts_path,
            minute_bars_path=args.minute_bars_path,
            outcome_status_path=args.outcome_status_path,
            reports_dir=args.reports_dir,
            generated_at=generated_at,
            stale_pending_hours=args.stale_pending_hours,
        )
        paths.update(export_evidence_health_report(health, args.output_dir))
    if args.report_kind in {"reliability", "both"}:
        reliability = build_reliability_report(
            alerts_path=args.alerts_path,
            outcome_status_path=args.outcome_status_path,
            reports_dir=args.reports_dir,
            generated_at=generated_at,
            window_days=args.window_days,
        )
        paths.update(export_reliability_report(reliability, args.output_dir))
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
