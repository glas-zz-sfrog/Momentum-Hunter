from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH, load_active_monitor_status
from momentum_hunter.active_monitor_runner import ACTIVE_MONITOR_RUNNER_PATH, load_active_monitor_runner_state
from momentum_hunter.alert_outcome_updater import ALERT_OUTCOME_UPDATE_STATUS_PATH, load_update_report
from momentum_hunter.alert_performance import build_alert_performance_report
from momentum_hunter.config import DATA_DIR
from momentum_hunter.evidence_autopilot import EVIDENCE_AUTOPILOT_STATUS_PATH, load_evidence_autopilot_status
from momentum_hunter.evidence_health import build_evidence_health_report, format_reason_counts
from momentum_hunter.monitor_targets import MONITOR_SYMBOLS_PATH, load_user_defined_symbols


def evidence_next_action_text(
    *,
    execution_ready_count: int,
    active_alert_count: int,
    outcome_count: int,
    performance_count: int,
    monitor_summary: str,
    evidence_summary: str,
) -> str:
    if execution_ready_count:
        return f"Next evidence action: review {execution_ready_count} execution-ready trade(s) in the Execution Ready tab."
    if active_alert_count:
        return f"Next evidence action: inspect {active_alert_count} active alert(s), then update outcomes when enough bars exist."
    if "NO CYCLE REPORT" in monitor_summary.upper():
        return "Next evidence action: run an Active Monitor cycle from Monitor + Health."
    if outcome_count and not performance_count:
        return "Next evidence action: update alert performance after outcomes complete."
    if "LOCKED" in evidence_summary.upper() or "COLLECTING" in evidence_summary.upper():
        return "Next evidence action: keep collecting evidence; optimization remains locked until enough completed outcomes exist."
    return "Next evidence action: review Monitor + Health first, then use detail tabs only when something needs attention."


def load_active_alert_rows(path: Path | None = None, *, limit: int = 10) -> list[dict[str, Any]]:
    path = path or DATA_DIR / "opportunity-alerts.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = []
    for item in payload.get("alerts", []):
        if not isinstance(item, dict):
            continue
        outcome = item.get("outcome") or {}
        if outcome.get("status", "PENDING_OUTCOME") not in {"PENDING_OUTCOME", "ACTIVE"}:
            continue
        rows.append(item)
    return sorted(rows, key=lambda item: str(item.get("timestamp", "")), reverse=True)[:limit]


def load_alert_outcome_rows(path: Path | None = None, *, limit: int = 10) -> list[dict[str, Any]]:
    path = path or DATA_DIR / "opportunity-alerts.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = [item for item in payload.get("alerts", []) if isinstance(item, dict)]
    return sorted(rows, key=lambda item: str(item.get("timestamp", "")), reverse=True)[:limit]


def load_alert_leaderboard_rows(path: Path | None = None, *, limit: int = 5) -> list[dict[str, Any]]:
    path = path or latest_opportunity_alert_json_path()
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = []
    for side, key in (("Best", "best_performing_alert_types"), ("Worst", "worst_performing_alert_types")):
        for item in payload.get(key, [])[:limit]:
            if isinstance(item, dict):
                row = dict(item)
                row["side"] = side
                rows.append(row)
    return rows


def alert_performance_summary_text(path: Path | None = None) -> str:
    try:
        report = build_alert_performance_report(path or (DATA_DIR / "opportunity-alerts.json"))
    except (json.JSONDecodeError, OSError, ValueError):
        return "ALERT PERFORMANCE: unable to read alert outcome data"
    if report.total_alerts == 0:
        return "ALERT PERFORMANCE: no alerts recorded yet"
    warning = " Diagnostic only." if report.current_sample_size < 20 else ""
    return (
        f"ALERT PERFORMANCE: {report.total_alerts} alert(s), "
        f"{report.completed_alerts} completed, {report.pending_alerts} pending, "
        f"{report.unscorable_alerts} unscorable. "
        f"Sample size: {report.current_sample_size}. Edge status: {report.measurable_edge_status}.{warning}"
    )


def load_alert_performance_dashboard_rows(path: Path | None = None, *, limit: int = 3) -> list[dict[str, Any]]:
    try:
        report = build_alert_performance_report(path or (DATA_DIR / "opportunity-alerts.json"))
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    rows: list[dict[str, Any]] = []
    for section, source_rows in (
        ("Best Alert Types", report.best_alert_types),
        ("Worst Alert Types", report.worst_alert_types),
        ("Best Symbols", report.best_symbols),
        ("Worst Symbols", report.worst_symbols),
    ):
        for item in source_rows[:limit]:
            rows.append(
                {
                    "section": section,
                    "group": item.group,
                    "alert_count": item.alert_count,
                    "completed_count": item.completed_count,
                    "win_rate_pct": item.win_rate_pct,
                    "average_60m_return_pct": item.average_60m_return_pct,
                    "average_mfe_pct": item.average_mfe_pct,
                    "average_mae_pct": item.average_mae_pct,
                }
            )
    return rows


def evidence_autopilot_summary_text(path: Path | None = None) -> str:
    status = load_evidence_autopilot_status(path or EVIDENCE_AUTOPILOT_STATUS_PATH)
    if status is None:
        return "EVIDENCE AUTOPILOT: no run yet"
    if status.state == "FAILED":
        return f"EVIDENCE AUTOPILOT: FAILED. {status.last_error}"
    if status.state == "RUNNING":
        return f"EVIDENCE AUTOPILOT: RUNNING since {status.started_at}"
    return (
        f"EVIDENCE AUTOPILOT: {status.state}. "
        f"{status.new_alert_count} new alert(s), {status.completed_outcome_count} completed outcome(s), "
        f"{status.pending_alert_count} pending, {status.unscorable_alert_count} unscorable. Updated {status.updated_at}."
    )


def load_evidence_autopilot_dashboard_rows(path: Path | None = None) -> list[dict[str, str]]:
    status = load_evidence_autopilot_status(path or EVIDENCE_AUTOPILOT_STATUS_PATH)
    if status is None:
        return []
    return [
        {
            "metric": "State",
            "value": status.state,
            "note": status.last_error or status.updated_at,
            "severity": "warn" if status.state == "FAILED" else "good",
        },
        {
            "metric": "Pipeline",
            "value": (
                f"M:{yes_no(status.monitor_cycle_completed)} "
                f"O:{yes_no(status.outcome_update_completed)} "
                f"E:{yes_no(status.evidence_report_generated)} "
                f"B:{yes_no(status.daily_brief_generated)}"
            ),
            "note": "monitor / outcome / evidence / brief",
            "severity": "good"
            if (
                status.monitor_cycle_completed
                and status.outcome_update_completed
                and status.evidence_report_generated
                and status.daily_brief_generated
            )
            else "warn",
        },
        {
            "metric": "Alerts",
            "value": f"{status.new_alert_count} new / {status.active_alert_count} active / {status.tracked_alert_count} tracked",
            "note": (
                f"{status.completed_outcome_count} completed; "
                f"{status.pending_alert_count} pending; {status.unscorable_alert_count} unscorable"
            ),
            "severity": "warn" if status.pending_alert_count else "good",
        },
        {
            "metric": "Data Issues",
            "value": f"{status.warning_count} warning(s)",
            "note": "; ".join(status.warnings[:2]) if status.warnings else "none",
            "severity": "warn" if status.warning_count else "good",
        },
        {
            "metric": "Daily Brief",
            "value": Path(status.daily_brief_path).name if status.daily_brief_path else "none",
            "note": status.daily_brief_path,
            "severity": "good" if status.daily_brief_path else "warn",
        },
    ]


def evidence_health_summary_text(path: Path | None = None) -> str:
    try:
        report = build_evidence_health_report(alerts_path=path or (DATA_DIR / "opportunity-alerts.json"))
    except (json.JSONDecodeError, OSError, ValueError):
        return "EVIDENCE HEALTH: unable to read alert evidence data"
    gate = report.evidence_gate
    return (
        f"EVIDENCE HEALTH: {report.completed_alerts}/{gate.required_alerts} completed alert(s), "
        f"{report.pending_alerts} pending, {report.unscorable_alerts} unscorable. Status: {gate.evidence_status}. "
        f"Optimization: {gate.strategy_optimization_status}."
    )


def load_evidence_health_dashboard_rows(path: Path | None = None) -> list[dict[str, str]]:
    try:
        report = build_evidence_health_report(alerts_path=path or (DATA_DIR / "opportunity-alerts.json"))
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    gate = report.evidence_gate
    warning_count = len(report.warnings)
    return [
        {
            "metric": "Completed Alerts",
            "value": f"{report.completed_alerts} / {gate.required_alerts}",
            "note": gate.allowed_action,
            "severity": "good" if report.completed_alerts >= gate.required_alerts else "warn",
        },
        {
            "metric": "Completion Rate",
            "value": "n/a" if report.completion_rate_pct is None else f"{report.completion_rate_pct}%",
            "note": f"{report.total_alerts} total; {report.pending_alerts} pending; {report.unscorable_alerts} unscorable",
            "severity": "good" if report.pending_alerts == 0 and report.total_alerts else "warn",
        },
        {
            "metric": "Unscorable Alerts",
            "value": str(report.unscorable_alerts),
            "note": format_reason_counts(report.unscorable_by_reason),
            "severity": "warn" if report.unscorable_alerts else "good",
        },
        {
            "metric": "Alert Funnel",
            "value": f"{report.alerts_generated} -> {report.alerts_captured} -> {report.alerts_classified} -> {report.completed_outcomes}",
            "note": "generated -> captured -> classified -> completed",
            "severity": "good" if report.alerts_generated == report.completed_outcomes and report.alerts_generated else "warn",
        },
        {
            "metric": "Data Issues",
            "value": str(warning_count),
            "note": "; ".join(report.warnings[:2]) if report.warnings else "none",
            "severity": "warn" if warning_count else "good",
        },
        {
            "metric": "Optimization Gate",
            "value": gate.strategy_optimization_status,
            "note": gate.reason,
            "severity": "warn" if gate.strategy_optimization_status == "LOCKED" else "good",
        },
    ]


def alert_outcome_update_status_text(path: Path | None = None) -> str:
    report = load_update_report(path or ALERT_OUTCOME_UPDATE_STATUS_PATH)
    if report is None:
        return "OUTCOME UPDATE: not run yet"
    warning_note = f", {len(report.warnings)} warning(s)" if report.warnings else ""
    return (
        f"OUTCOME UPDATE: {report.updated_alert_count} changed, "
        f"{report.completed_alert_count} completed, {report.pending_alert_count} pending, "
        f"{report.unscorable_alert_count} unscorable, "
        f"{report.bars_loaded_count} minute bar(s){warning_note}"
    )


def latest_opportunity_alert_json_path() -> Path | None:
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("opportunity-alerts-*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def latest_active_monitor_cycle_json_path() -> Path | None:
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("active-monitor-cycle-*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def load_active_monitor_cycle(path: Path | None = None) -> dict[str, Any]:
    path = path or latest_active_monitor_cycle_json_path()
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    cycle = payload.get("monitor_cycle", {})
    return cycle if isinstance(cycle, dict) else {}


def active_monitor_summary_text(path: Path | None = None) -> str:
    cycle = load_active_monitor_cycle(path)
    if not cycle:
        return "ACTIVE MONITOR: NO CYCLE REPORT YET"
    target_count = int_or_zero(cycle.get("target_count"))
    active_alerts = int_or_zero(cycle.get("active_alert_count"))
    new_alerts = int_or_zero(cycle.get("new_alert_count"))
    coverage_rows = int_or_zero(cycle.get("coverage_row_count"))
    warnings = cycle.get("warnings") if isinstance(cycle.get("warnings"), list) else []
    if active_alerts or new_alerts:
        return f"ACTIVE MONITOR: {active_alerts} active alert(s), {new_alerts} new alert(s), {target_count} target(s)"
    if "COVERAGE_ROWS_WITHOUT_MARKET_DATA" in warnings:
        return f"ACTIVE MONITOR: {target_count} target(s), {coverage_rows} coverage row(s) need market tape"
    return f"ACTIVE MONITOR: {target_count} target(s), no active alerts"


def load_active_monitor_dashboard_rows(path: Path | None = None) -> list[dict[str, str]]:
    cycle = load_active_monitor_cycle(path)
    runtime_rows = active_monitor_runtime_rows() if path is None else []
    if not cycle:
        return runtime_rows
    warnings = cycle.get("warnings") if isinstance(cycle.get("warnings"), list) else []
    missing = list_of_strings(cycle.get("missing_target_symbols"))
    covered = list_of_strings(cycle.get("covered_missing_symbols"))
    uncovered = list_of_strings(cycle.get("uncovered_missing_symbols"))
    rows = runtime_rows + [
        {
            "metric": "Generated",
            "value": str(cycle.get("generated_at", "")),
            "note": Path(str(cycle.get("trade_report_path", ""))).name if cycle.get("trade_report_path") else "",
            "severity": "good",
        },
        {
            "metric": "Targets",
            "value": str(cycle.get("target_count", 0)),
            "note": ", ".join(list_of_strings(cycle.get("target_symbols"))) or "none",
            "severity": "good" if int_or_zero(cycle.get("target_count")) else "warn",
        },
        {
            "metric": "Matched / Covered",
            "value": f"{cycle.get('matched_target_count', 0)} / {cycle.get('target_count', 0)}",
            "note": f"coverage rows: {cycle.get('coverage_row_count', 0)}",
            "severity": "warn" if uncovered else "good",
        },
        {
            "metric": "Missing Source Rows",
            "value": str(len(missing)),
            "note": ", ".join(missing) if missing else "none",
            "severity": "warn" if missing else "good",
        },
        {
            "metric": "Covered Missing",
            "value": str(len(covered)),
            "note": ", ".join(covered) if covered else "none",
            "severity": "warn" if "COVERAGE_ROWS_WITHOUT_MARKET_DATA" in warnings else "good",
        },
        {
            "metric": "Refreshed Targets",
            "value": str(cycle.get("refreshed_target_count", 0)),
            "note": (
                f"readiness changed: {cycle.get('readiness_changed_count', 0)}; "
                f"{Path(str(cycle.get('market_data_refresh_report_path', ''))).name if cycle.get('market_data_refresh_report_path') else 'none'}"
            ),
            "severity": "warn"
            if int_or_zero(cycle.get("readiness_changed_count"))
            else ("good" if int_or_zero(cycle.get("refreshed_target_count")) else ""),
        },
        {
            "metric": "Alerts",
            "value": f"{cycle.get('active_alert_count', 0)} active / {cycle.get('new_alert_count', 0)} new",
            "note": f"{cycle.get('tracked_alert_count', 0)} tracked; {cycle.get('state_transition_count', 0)} state transition(s)",
            "severity": "warn"
            if int_or_zero(cycle.get("active_alert_count")) or int_or_zero(cycle.get("new_alert_count"))
            else "good",
        },
    ]
    if warnings:
        rows.append(
            {
                "metric": "Warnings",
                "value": str(len(warnings)),
                "note": "; ".join(str(item) for item in warnings[:3]),
                "severity": "warn",
            }
        )
    return rows


def active_monitor_runtime_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    runner = load_active_monitor_runner_state(ACTIVE_MONITOR_RUNNER_PATH)
    status = load_active_monitor_status(ACTIVE_MONITOR_STATUS_PATH)
    if runner:
        rows.append(
            {
                "metric": "Background",
                "value": f"{runner.state} PID {runner.pid}",
                "note": (
                    f"every {runner.interval_seconds}s; missing quotes "
                    f"{'on' if runner.fetch_missing_market_data else 'off'}; target refresh "
                    f"{'on' if runner.refresh_target_market_data else 'off'}"
                ),
                "severity": "good" if runner.state == "RUNNING" else ("warn" if runner.state == "FAILED" else ""),
            }
        )
    if status:
        note = status.last_error or f"cycles {status.cycles_completed}/{status.cycles_requested}"
        if status.next_cycle_at:
            note = f"next {status.next_cycle_at}; {note}"
        rows.append(
            {
                "metric": "Loop Status",
                "value": status.state,
                "note": note,
                "severity": "warn" if status.state == "FAILED" else ("good" if status.state in {"RUNNING", "IDLE"} else ""),
            }
        )
    return rows


def load_user_monitor_symbol_rows(path: Path | None = None) -> list[dict[str, str]]:
    try:
        symbols = load_user_defined_symbols(path or MONITOR_SYMBOLS_PATH)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    return [
        {
            "symbol": item.symbol,
            "enabled": "yes" if item.enabled else "no",
            "notes": item.notes,
            "added_at": item.added_at,
        }
        for item in sorted(symbols.values(), key=lambda record: record.symbol)
    ]


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def int_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
