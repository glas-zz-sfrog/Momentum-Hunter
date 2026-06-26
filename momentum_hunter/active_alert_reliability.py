from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.active_monitor import (
    ACTIVE_MONITOR_STATUS_PATH,
    latest_monitor_cycle_json_path,
    load_active_monitor_status,
)
from momentum_hunter.alert_outcome_updater import ALERT_OUTCOME_UPDATE_STATUS_PATH, load_update_report
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OpportunityAlert,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
    parse_datetime,
    stable_alert_id,
)
from momentum_hunter.sqlite_validation import SQLITE_VALIDATION_LATEST_JSON, build_sqlite_validation_report
from momentum_hunter.time_utils import now_central


ACTIVE_ALERT_RELIABILITY_SCHEMA_VERSION = 1
ACTIVE_ALERT_RELIABILITY_VERSION = "active_alert_reliability_v1"
ACTIVE_ALERT_RELIABILITY_LATEST_JSON = DATA_DIR / "reports" / "active-alert-reliability-latest.json"
ACTIVE_ALERT_RELIABILITY_LATEST_MD = DATA_DIR / "reports" / "active-alert-reliability-latest.md"
STALE_ACTIVE_MONITOR_CYCLE_MINUTES = 24 * 60


@dataclass(frozen=True)
class ActiveAlertReliabilityReport:
    generated_at: str
    overall_status: str
    active_monitor_status_path: str
    active_monitor_state: str
    active_monitor_last_cycle_at: str
    active_monitor_cycle_age_minutes: float | None
    active_monitor_last_report_path: str
    latest_cycle_report_path: str
    latest_cycle_target_count: int
    latest_cycle_new_alert_count: int
    latest_cycle_active_alert_count: int
    latest_cycle_tracked_alert_count: int
    latest_cycle_state_transition_count: int
    latest_cycle_coverage_row_count: int
    latest_cycle_warnings: list[str]
    alerts_path: str
    alert_count: int
    completed_alert_count: int
    pending_alert_count: int
    unscorable_alert_count: int
    active_alert_count: int
    duplicate_alert_ids: list[str]
    duplicate_semantic_keys: list[str]
    unstable_alert_ids: list[str]
    missing_price_alert_ids: list[str]
    invalid_timestamp_alert_ids: list[str]
    missing_source_report_alert_ids: list[str]
    missing_source_report_paths: list[str]
    pending_alert_ids: list[str]
    unscorable_alert_ids: list[str]
    outcome_status_path: str
    outcome_status_generated_at: str
    outcome_status_alert_count: int
    outcome_status_completed_count: int
    outcome_status_pending_count: int
    outcome_status_unscorable_count: int
    outcome_status_warnings: list[str]
    sqlite_validation_path: str
    sqlite_validation_status: str
    sqlite_alert_check_status: str
    sqlite_outcome_check_status: str
    sqlite_warnings: list[str]
    warnings: list[str] = field(default_factory=list)
    next_recommended_action: str = ""


def build_active_alert_reliability_report(
    *,
    status_path: Path = ACTIVE_MONITOR_STATUS_PATH,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    outcome_status_path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH,
    reports_dir: Path | None = None,
    sqlite_validation_path: Path = SQLITE_VALIDATION_LATEST_JSON,
    generated_at: datetime | None = None,
) -> ActiveAlertReliabilityReport:
    generated_at = generated_at or now_central()
    reports_dir = reports_dir or DATA_DIR / "reports"
    status = load_active_monitor_status(status_path)
    latest_cycle_path = latest_monitor_cycle_json_path(reports_dir)
    latest_cycle = load_latest_cycle_payload(latest_cycle_path)
    alerts, alert_load_warnings = load_alerts_safely(alerts_path)
    outcome_status = load_update_report(outcome_status_path)
    sqlite_validation = sqlite_validation_payload(sqlite_validation_path)

    duplicate_alert_ids = duplicate_values([alert.alert_id for alert in alerts if alert.alert_id])
    duplicate_semantic_keys = duplicate_values([semantic_key(alert) for alert in alerts])
    unstable_alert_ids = [
        alert.alert_id
        for alert in alerts
        if alert.alert_id and alert.alert_id != stable_alert_id(alert.symbol, alert.timestamp, alert.alert_type)
    ]
    missing_price_alert_ids = [alert.alert_id for alert in alerts if alert.price is None or alert.price <= 0]
    invalid_timestamp_alert_ids = [alert.alert_id for alert in alerts if parse_datetime(alert.timestamp) is None]
    missing_source_report_alert_ids = [alert.alert_id for alert in alerts if not alert.source_report]
    missing_source_report_paths = sorted(
        {
            alert.source_report
            for alert in alerts
            if alert.source_report and not Path(alert.source_report).exists()
        }
    )
    pending_alert_ids = [alert.alert_id for alert in alerts if is_pending_alert(alert)]
    unscorable_alert_ids = [alert.alert_id for alert in alerts if is_unscorable_alert(alert)]
    completed_alert_count = sum(1 for alert in alerts if is_completed_alert(alert))
    pending_alert_count = len(pending_alert_ids)
    unscorable_alert_count = len(unscorable_alert_ids)
    active_alert_count = pending_alert_count

    sqlite_alert_check = sqlite_check_status(sqlite_validation, "opportunity_alerts")
    sqlite_outcome_check = sqlite_check_status(sqlite_validation, "alert_outcomes")
    cycle_age = timestamp_age_minutes(status.last_cycle_at if status else "", generated_at)
    warnings: list[str] = []
    warnings.extend(alert_load_warnings)
    if status is None:
        warnings.append("NO_ACTIVE_MONITOR_STATUS")
    else:
        if status.state.upper() == "FAILED":
            warnings.append("ACTIVE_MONITOR_FAILED")
        if status.warnings:
            warnings.append("ACTIVE_MONITOR_WARNINGS_PRESENT")
        if cycle_age is not None and cycle_age > STALE_ACTIVE_MONITOR_CYCLE_MINUTES:
            warnings.append("STALE_ACTIVE_MONITOR_CYCLE")
    if latest_cycle_path is None:
        warnings.append("NO_LATEST_MONITOR_CYCLE_REPORT")
    elif not latest_cycle:
        warnings.append("LATEST_MONITOR_CYCLE_REPORT_UNREADABLE")
    if duplicate_alert_ids:
        warnings.append("DUPLICATE_ALERT_IDS")
    if duplicate_semantic_keys:
        warnings.append("DUPLICATE_ALERT_SEMANTIC_KEYS")
    if unstable_alert_ids:
        warnings.append("ALERT_IDS_NOT_STABLE")
    if missing_price_alert_ids:
        warnings.append("ALERTS_MISSING_PRICE")
    if invalid_timestamp_alert_ids:
        warnings.append("ALERTS_INVALID_TIMESTAMP")
    if missing_source_report_alert_ids:
        warnings.append("ALERTS_MISSING_SOURCE_REPORT")
    if missing_source_report_paths:
        warnings.append("ALERT_SOURCE_REPORT_FILES_MISSING")
    if pending_alert_ids:
        warnings.append("PENDING_ALERTS_WAITING_FOR_OUTCOMES")
    if unscorable_alert_ids:
        warnings.append("UNSCORABLE_ALERTS_PRESENT")
    if outcome_status is None:
        warnings.append("NO_ALERT_OUTCOME_UPDATE_STATUS")
    elif outcome_status.warnings:
        warnings.append("ALERT_OUTCOME_UPDATE_WARNINGS_PRESENT")
    sqlite_status = str(sqlite_validation.get("overall_status") or "UNKNOWN")
    if sqlite_status != "PASS":
        warnings.append("SQLITE_VALIDATION_NOT_PASS")
    if sqlite_alert_check != "PASS":
        warnings.append("SQLITE_ALERT_MIRROR_NOT_PASS")
    if sqlite_outcome_check != "PASS":
        warnings.append("SQLITE_OUTCOME_MIRROR_NOT_PASS")

    overall = overall_status(warnings, status.state if status else "")
    return ActiveAlertReliabilityReport(
        generated_at=generated_at.isoformat(),
        overall_status=overall,
        active_monitor_status_path=str(status_path),
        active_monitor_state=status.state if status else "UNKNOWN",
        active_monitor_last_cycle_at=status.last_cycle_at if status else "",
        active_monitor_cycle_age_minutes=cycle_age,
        active_monitor_last_report_path=status.last_report_path if status else "",
        latest_cycle_report_path=str(latest_cycle_path or ""),
        latest_cycle_target_count=int_value(latest_cycle.get("target_count")),
        latest_cycle_new_alert_count=int_value(latest_cycle.get("new_alert_count")),
        latest_cycle_active_alert_count=int_value(latest_cycle.get("active_alert_count")),
        latest_cycle_tracked_alert_count=int_value(latest_cycle.get("tracked_alert_count")),
        latest_cycle_state_transition_count=int_value(latest_cycle.get("state_transition_count")),
        latest_cycle_coverage_row_count=int_value(latest_cycle.get("coverage_row_count")),
        latest_cycle_warnings=[str(item) for item in latest_cycle.get("warnings", [])]
        if isinstance(latest_cycle.get("warnings"), list)
        else [],
        alerts_path=str(alerts_path),
        alert_count=len(alerts),
        completed_alert_count=completed_alert_count,
        pending_alert_count=pending_alert_count,
        unscorable_alert_count=unscorable_alert_count,
        active_alert_count=active_alert_count,
        duplicate_alert_ids=duplicate_alert_ids,
        duplicate_semantic_keys=duplicate_semantic_keys,
        unstable_alert_ids=unstable_alert_ids,
        missing_price_alert_ids=missing_price_alert_ids,
        invalid_timestamp_alert_ids=invalid_timestamp_alert_ids,
        missing_source_report_alert_ids=missing_source_report_alert_ids,
        missing_source_report_paths=missing_source_report_paths,
        pending_alert_ids=pending_alert_ids,
        unscorable_alert_ids=unscorable_alert_ids,
        outcome_status_path=str(outcome_status_path),
        outcome_status_generated_at=outcome_status.generated_at if outcome_status else "",
        outcome_status_alert_count=outcome_status.alert_count if outcome_status else 0,
        outcome_status_completed_count=outcome_status.completed_alert_count if outcome_status else 0,
        outcome_status_pending_count=outcome_status.pending_alert_count if outcome_status else 0,
        outcome_status_unscorable_count=outcome_status.unscorable_alert_count if outcome_status else 0,
        outcome_status_warnings=list(outcome_status.warnings) if outcome_status else [],
        sqlite_validation_path=str(sqlite_validation_path),
        sqlite_validation_status=sqlite_status,
        sqlite_alert_check_status=sqlite_alert_check,
        sqlite_outcome_check_status=sqlite_outcome_check,
        sqlite_warnings=[str(item) for item in sqlite_validation.get("warnings", [])]
        if isinstance(sqlite_validation.get("warnings"), list)
        else [],
        warnings=dedupe(warnings),
        next_recommended_action=next_action(warnings, pending_alert_count, unscorable_alert_count),
    )


def load_latest_cycle_payload(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    cycle = payload.get("monitor_cycle", payload)
    return cycle if isinstance(cycle, dict) else {}


def load_alerts_safely(path: Path) -> tuple[list[OpportunityAlert], list[str]]:
    try:
        return load_alerts(path), []
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return [], [f"ALERT_STORE_READ_FAILED:{type(exc).__name__}"]


def sqlite_validation_payload(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (json.JSONDecodeError, OSError):
            pass
    try:
        payload = build_sqlite_validation_report()
    except Exception as exc:  # pragma: no cover - defensive guard for CLI/report use
        return {"overall_status": "UNKNOWN", "warnings": [f"SQLITE_VALIDATION_UNAVAILABLE:{type(exc).__name__}:{exc}"]}
    return payload if isinstance(payload, dict) else {"overall_status": "UNKNOWN", "warnings": ["SQLITE_VALIDATION_UNAVAILABLE"]}


def sqlite_check_status(payload: dict[str, Any], name: str) -> str:
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        return "UNKNOWN"
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return str(check.get("status") or "UNKNOWN")
    return "UNKNOWN"


def semantic_key(alert: OpportunityAlert) -> str:
    return "|".join([alert.symbol, alert.timestamp, alert.alert_type])


def duplicate_values(values: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(value for value, count in counts.items() if count > 1)


def timestamp_age_minutes(value: str, generated_at: datetime) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return round((generated_at - timestamp).total_seconds() / 60, 3)


def int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def overall_status(warnings: list[str], monitor_state: str) -> str:
    if monitor_state.upper() == "FAILED" or "ALERT_STORE_READ_FAILED" in " ".join(warnings):
        return "FAILED"
    severe = {"DUPLICATE_ALERT_IDS", "ALERTS_INVALID_TIMESTAMP", "SQLITE_ALERT_MIRROR_NOT_PASS", "SQLITE_OUTCOME_MIRROR_NOT_PASS"}
    if any(warning in severe for warning in warnings):
        return "FAILED"
    return "WARNING" if warnings else "READY"


def next_action(warnings: list[str], pending_count: int, unscorable_count: int) -> str:
    if "NO_ACTIVE_MONITOR_STATUS" in warnings:
        return "Run the active monitor once and confirm it writes active-monitor-status.json."
    if "STALE_ACTIVE_MONITOR_CYCLE" in warnings:
        return "Run a fresh active monitor cycle before trusting current alert state."
    if "DUPLICATE_ALERT_IDS" in warnings or "ALERT_IDS_NOT_STABLE" in warnings:
        return "Audit alert identity generation before using alert performance analytics."
    if pending_count:
        return "Run the alert outcome updater when post-alert minute bars are available."
    if unscorable_count:
        return "Review unscorable alerts as data-quality loss; keep them out of performance thresholds."
    if "SQLITE_VALIDATION_NOT_PASS" in warnings:
        return "Refresh safe SQLite imports and rerun validation before trusting SQLite mirrors."
    return "Active alert evidence chain is usable for monitoring; continue collecting more outcomes."


def export_active_alert_reliability_report(
    report: ActiveAlertReliabilityReport,
    *,
    json_path: Path = ACTIVE_ALERT_RELIABILITY_LATEST_JSON,
    markdown_path: Path = ACTIVE_ALERT_RELIABILITY_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ACTIVE_ALERT_RELIABILITY_SCHEMA_VERSION,
        "engine_version": ACTIVE_ALERT_RELIABILITY_VERSION,
        "report": asdict(report),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_active_alert_reliability_markdown(report), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def format_active_alert_reliability_markdown(report: ActiveAlertReliabilityReport) -> str:
    lines = [
        "# Momentum Hunter Active Alert Reliability",
        "",
        "Read-only reliability report. This does not generate alerts, change thresholds, place orders, or mutate raw captures.",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Overall status: {report.overall_status}",
        f"- Next action: {report.next_recommended_action}",
        "",
        "## Active Monitor",
        "",
        f"- Status path: `{report.active_monitor_status_path}`",
        f"- State: {report.active_monitor_state}",
        f"- Last cycle: {report.active_monitor_last_cycle_at or 'n/a'}",
        f"- Last cycle age minutes: {format_optional_float(report.active_monitor_cycle_age_minutes)}",
        f"- Last cycle report: `{report.latest_cycle_report_path or 'none'}`",
        f"- Targets: {report.latest_cycle_target_count}",
        f"- New alerts: {report.latest_cycle_new_alert_count}",
        f"- Active alerts in cycle: {report.latest_cycle_active_alert_count}",
        f"- Tracked alerts in cycle: {report.latest_cycle_tracked_alert_count}",
        f"- State transitions: {report.latest_cycle_state_transition_count}",
        f"- Coverage rows: {report.latest_cycle_coverage_row_count}",
        "",
        "## Alert Store",
        "",
        f"- Alerts path: `{report.alerts_path}`",
        f"- Total alerts: {report.alert_count}",
        f"- Completed alerts: {report.completed_alert_count}",
        f"- Pending alerts: {report.pending_alert_count}",
        f"- Unscorable alerts: {report.unscorable_alert_count}",
        f"- Duplicate alert IDs: {len(report.duplicate_alert_ids)}",
        f"- Duplicate semantic keys: {len(report.duplicate_semantic_keys)}",
        f"- Unstable alert IDs: {len(report.unstable_alert_ids)}",
        f"- Missing price alerts: {len(report.missing_price_alert_ids)}",
        f"- Invalid timestamp alerts: {len(report.invalid_timestamp_alert_ids)}",
        f"- Missing source report alerts: {len(report.missing_source_report_alert_ids)}",
        "",
        "## Outcome Handoff",
        "",
        f"- Outcome status path: `{report.outcome_status_path}`",
        f"- Generated at: {report.outcome_status_generated_at or 'n/a'}",
        f"- Outcome status alerts: {report.outcome_status_alert_count}",
        f"- Outcome completed: {report.outcome_status_completed_count}",
        f"- Outcome pending: {report.outcome_status_pending_count}",
        f"- Outcome unscorable: {report.outcome_status_unscorable_count}",
        "",
        "## SQLite Mirror",
        "",
        f"- Validation path: `{report.sqlite_validation_path}`",
        f"- Validation status: {report.sqlite_validation_status}",
        f"- Opportunity alert check: {report.sqlite_alert_check_status}",
        f"- Alert outcome check: {report.sqlite_outcome_check_status}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] if report.warnings else ["- None."])
    lines.extend(["", "## Detail Lists", ""])
    detail_sections = [
        ("Pending alerts", report.pending_alert_ids),
        ("Unscorable alerts", report.unscorable_alert_ids),
        ("Duplicate alert IDs", report.duplicate_alert_ids),
        ("Duplicate semantic keys", report.duplicate_semantic_keys),
        ("Unstable alert IDs", report.unstable_alert_ids),
        ("Missing price alert IDs", report.missing_price_alert_ids),
        ("Invalid timestamp alert IDs", report.invalid_timestamp_alert_ids),
        ("Missing source report paths", report.missing_source_report_paths),
    ]
    for title, values in detail_sections:
        lines.extend([f"### {title}", ""])
        lines.extend([f"- {value}" for value in values] if values else ["- None."])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter active-alert reliability report.")
    parser.add_argument("--status-path", type=Path, default=ACTIVE_MONITOR_STATUS_PATH)
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--outcome-status-path", type=Path, default=ALERT_OUTCOME_UPDATE_STATUS_PATH)
    parser.add_argument("--reports-dir", type=Path, default=DATA_DIR / "reports")
    parser.add_argument("--sqlite-validation-path", type=Path, default=SQLITE_VALIDATION_LATEST_JSON)
    parser.add_argument("--json", type=Path, default=ACTIVE_ALERT_RELIABILITY_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=ACTIVE_ALERT_RELIABILITY_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_active_alert_reliability_report(
        status_path=args.status_path,
        alerts_path=args.alerts_path,
        outcome_status_path=args.outcome_status_path,
        reports_dir=args.reports_dir,
        sqlite_validation_path=args.sqlite_validation_path,
    )
    paths = export_active_alert_reliability_report(report, json_path=args.json, markdown_path=args.markdown)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
