from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.capture_health import build_capture_health_snapshot
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.report_index import REPORT_INDEX_LATEST_JSON
from momentum_hunter.system_readiness import SYSTEM_READINESS_LATEST_JSON
from momentum_hunter.time_utils import now_central


OPERATIONAL_RELIABILITY_SCHEMA_VERSION = 1
OPERATIONAL_RELIABILITY_ENGINE_VERSION = "operational_reliability_sprint_v1"
REPORTS_DIR = DATA_DIR / "reports"
OPERATIONAL_RELIABILITY_LATEST_JSON = REPORTS_DIR / "operational-reliability-sprint-v1-final-report.json"
OPERATIONAL_RELIABILITY_LATEST_MD = REPORTS_DIR / "operational-reliability-sprint-v1-final-report.md"

ACTIVE_ALERT_RELIABILITY_LATEST_JSON = REPORTS_DIR / "active-alert-reliability-latest.json"
EVIDENCE_AUTOPILOT_LATEST_JSON = REPORTS_DIR / "evidence-autopilot-latest.json"
PROVIDER_FIELD_QUALITY_LATEST_JSON = REPORTS_DIR / "provider-field-quality-latest.json"
EVIDENCE_CENSUS_LATEST_JSON = REPORTS_DIR / "evidence-census-latest.json"
DATA_QUALITY_LATEST_JSON = REPORTS_DIR / "data-quality-latest.json"
ACTIVE_MONITOR_STATUS_PATH = DATA_DIR / "active-monitor-status.json"
OPPORTUNITY_ALERTS_PATH = DATA_DIR / "opportunity-alerts.json"

WARNING_CATEGORIES = {
    "EXPECTED",
    "ACTIONABLE",
    "STALE",
    "FAILED",
    "MARKET_HOURS_REQUIRED",
    "LEGACY_DATA_GAP",
    "UNKNOWN",
}


@dataclass(frozen=True)
class ClassifiedWarning:
    source: str
    warning: str
    category: str
    severity: str
    recommended_action: str
    evidence: str = ""


def classify_warning(warning: str, *, source: str = "") -> tuple[str, str, str]:
    text = f"{source} {warning}".upper()
    if any(
        marker in text
        for marker in (
            "REPORT_STATUS_FAIL",
            "REPORT_STATUS_FAILED",
            "STATE_FAILED",
            "_FAILED",
            "LAST_ERROR",
            "CURRENT_FAILURE",
            "UNREADABLE",
            "INVALID",
            "CORRUPT",
        )
    ):
        return "FAILED", "HIGH", "Open the source report and resolve the recorded failure before relying on the affected workflow."
    if any(marker in text for marker in ("MARKET_HOURS", "PREMARKET", "AFTER_HOURS")):
        return "MARKET_HOURS_REQUIRED", "MEDIUM", "Run this check during the appropriate market window before drawing live conclusions."
    if any(marker in text for marker in ("COVERAGE_ROWS_WITHOUT_MARKET_DATA", "NO MARKET TAPE", "MISSING MARKET TAPE", "QUOTE_HTTP_401")):
        return "MARKET_HOURS_REQUIRED", "MEDIUM", "Refresh market tape during a supported market-data window or validate provider access."
    if any(marker in text for marker in ("STALE", "REPORT_STALE", "OLD")):
        return "STALE", "MEDIUM", "Regenerate the stale report or rerun the associated backend job."
    if any(marker in text for marker in ("LEGACY", "UNTRACKED", "PRE_MANIFEST")):
        return "LEGACY_DATA_GAP", "LOW", "Preserve the legacy record, but exclude it from strict evidence claims unless it is explicitly validated."
    if any(marker in text for marker in ("LOW_COMPLETED_ALERT_SAMPLE", "INSUFFICIENT", "SAMPLE")):
        return "EXPECTED", "LOW", "Keep collecting evidence; do not optimize or recommend strategy changes yet."
    if any(
        marker in text
        for marker in (
            "NO NEW OPPORTUNITY ALERTS",
            "LATEST STATE: COMPLETED",
            "SKIPPED_UNSUPPORTED_SCHEMA",
            "RAW CAPTURE ALREADY EXISTS",
        )
    ):
        return "EXPECTED", "LOW", "Record this as expected operational behavior; no trading logic change is implied."
    if any(
        marker in text
        for marker in (
            "REPORT_STATUS_WARN",
            "REPORT_STATUS_WARNING",
            "STATUS IS WARNING",
            "STATUS IS WARN",
            "UNSCORABLE",
            "MISSING",
            "NO_",
            "PENDING",
            "CAPTURE FAILURE",
            "LAST FAILURE",
            "WARNINGS_PRESENT",
            "ZERO_",
            "TARGETS_WITHOUT_SOURCE_TRADE_ROWS",
            "MONITOR STATUS IS IDLE",
        )
    ):
        return "ACTIONABLE", "MEDIUM", "Review the referenced artifact and fix or accept the data-quality loss explicitly."
    if warning.strip():
        return "UNKNOWN", "LOW", "Review this warning and add a more specific classifier if it recurs."
    return "EXPECTED", "LOW", "No action required."


def build_operational_reliability_report(
    *,
    reports_dir: Path = REPORTS_DIR,
    data_dir: Path = DATA_DIR,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central().isoformat()
    items: list[ClassifiedWarning] = []
    items.extend(classified_report_index_warnings(reports_dir / REPORT_INDEX_LATEST_JSON.name))
    items.extend(classified_system_readiness_warnings(reports_dir / SYSTEM_READINESS_LATEST_JSON.name))
    items.extend(classified_provider_warnings(reports_dir / PROVIDER_FIELD_QUALITY_LATEST_JSON.name))
    items.extend(classified_data_quality_warnings(reports_dir / DATA_QUALITY_LATEST_JSON.name))
    items.extend(classified_generic_report_warnings("Evidence Autopilot", reports_dir / EVIDENCE_AUTOPILOT_LATEST_JSON.name))
    items.extend(classified_generic_report_warnings("Active Alert Reliability", reports_dir / ACTIVE_ALERT_RELIABILITY_LATEST_JSON.name))
    items.extend(classified_generic_report_warnings("Evidence Census", reports_dir / EVIDENCE_CENSUS_LATEST_JSON.name))
    items.extend(classified_active_monitor_warnings(data_dir / ACTIVE_MONITOR_STATUS_PATH.name))
    items.extend(classified_alert_store_warnings(data_dir / OPPORTUNITY_ALERTS_PATH.name))
    items.extend(classified_capture_health_warnings())

    category_counts = Counter(item.category for item in items)
    severity_counts = Counter(item.severity for item in items)
    actionable_count = sum(
        category_counts.get(category, 0)
        for category in ("ACTIONABLE", "STALE", "FAILED", "MARKET_HOURS_REQUIRED", "UNKNOWN")
    )
    overall_status = "PASS"
    if category_counts.get("FAILED", 0):
        overall_status = "FAIL"
    elif actionable_count:
        overall_status = "WARN"
    return {
        "schema_version": OPERATIONAL_RELIABILITY_SCHEMA_VERSION,
        "engine_version": OPERATIONAL_RELIABILITY_ENGINE_VERSION,
        "generated_at": generated_at,
        "overall_status": overall_status,
        "category_counts": {category: category_counts.get(category, 0) for category in sorted(WARNING_CATEGORIES)},
        "severity_counts": dict(sorted(severity_counts.items())),
        "total_warnings": len(items),
        "actionable_warning_count": actionable_count,
        "warnings": [asdict(item) for item in items],
        "next_actions": recommended_next_actions(items),
        "source_paths": {
            "report_index": str(reports_dir / REPORT_INDEX_LATEST_JSON.name),
            "system_readiness": str(reports_dir / SYSTEM_READINESS_LATEST_JSON.name),
            "provider_field_quality": str(reports_dir / PROVIDER_FIELD_QUALITY_LATEST_JSON.name),
            "data_quality": str(reports_dir / DATA_QUALITY_LATEST_JSON.name),
            "evidence_autopilot": str(reports_dir / EVIDENCE_AUTOPILOT_LATEST_JSON.name),
            "active_alert_reliability": str(reports_dir / ACTIVE_ALERT_RELIABILITY_LATEST_JSON.name),
            "evidence_census": str(reports_dir / EVIDENCE_CENSUS_LATEST_JSON.name),
            "active_monitor_status": str(data_dir / ACTIVE_MONITOR_STATUS_PATH.name),
            "opportunity_alerts": str(data_dir / OPPORTUNITY_ALERTS_PATH.name),
        },
        "safety_note": (
            "Reporting-only classification. This does not change scoring, readiness, alerts, outcomes, "
            "trade planning, provider behavior, raw captures, or user-authored files."
        ),
    }


def classified_report_index_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    items: list[ClassifiedWarning] = []
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        items.append(make_warning("Report Index", str(warning), evidence=str(path)))
    for entry in payload.get("entries", []) if isinstance(payload.get("entries"), list) else []:
        if not isinstance(entry, dict):
            continue
        source = f"Report Index / {entry.get('name', 'unknown')}"
        evidence = str(entry.get("latest_path") or path)
        for warning in entry.get("warnings", []) if isinstance(entry.get("warnings"), list) else []:
            items.append(make_warning(source, str(warning), evidence=evidence))
    return items


def classified_system_readiness_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    report = payload.get("report", payload) if isinstance(payload, dict) else {}
    if not isinstance(report, dict):
        return []
    items: list[ClassifiedWarning] = []
    for warning in report.get("warnings", []) if isinstance(report.get("warnings"), list) else []:
        items.append(make_warning("System Readiness", str(warning), evidence=str(path)))
    for issue in report.get("issues_requiring_attention", []) if isinstance(report.get("issues_requiring_attention"), list) else []:
        items.append(make_warning("System Readiness", str(issue), evidence=str(path)))
    return dedupe_warnings(items)


def classified_provider_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    items: list[ClassifiedWarning] = []
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        items.append(make_warning("Provider Field Quality", str(warning), evidence=str(path)))
    for warning in payload.get("top_warnings", []) if isinstance(payload.get("top_warnings"), list) else []:
        if isinstance(warning, dict):
            items.append(
                make_warning(
                    "Provider Field Quality",
                    f"{warning.get('warning', 'UNKNOWN')}:{warning.get('count', 0)}",
                    evidence=str(path),
                )
            )
    return items


def classified_data_quality_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    items: list[ClassifiedWarning] = []
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        items.append(make_warning("Data Quality", str(warning), evidence=str(path)))
    provider_rows = payload.get("provider_rows") or payload.get("rows") or []
    if isinstance(provider_rows, list):
        for row in provider_rows[:250]:
            if isinstance(row, dict) and row.get("warnings"):
                for warning in row.get("warnings", []):
                    items.append(make_warning("Data Quality", str(warning), evidence=str(path)))
    return dedupe_warnings(items)


def classified_generic_report_warnings(source: str, path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    report = payload.get("report", payload) if isinstance(payload, dict) else {}
    if not isinstance(report, dict):
        return []
    items = [
        make_warning(source, str(warning), evidence=str(path))
        for warning in report.get("warnings", [])
        if isinstance(report.get("warnings"), list)
    ]
    status = str(report.get("overall_status") or report.get("status") or report.get("latest_run_state") or "")
    if status.upper() in {"WARN", "WARNING", "FAILED", "FAIL", "UNKNOWN"}:
        items.append(make_warning(source, f"REPORT_STATUS_{status}", evidence=str(path)))
    return dedupe_warnings(items)


def classified_active_monitor_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    items: list[ClassifiedWarning] = []
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        items.append(make_warning("Active Monitor", str(warning), evidence=str(path)))
    if payload.get("last_error"):
        items.append(make_warning("Active Monitor", f"LAST_ERROR:{payload.get('last_error')}", evidence=str(path)))
    state = str(payload.get("state") or "")
    if state.upper() in {"FAILED", "UNKNOWN"}:
        items.append(make_warning("Active Monitor", f"STATE_{state}", evidence=str(path)))
    return dedupe_warnings(items)


def classified_alert_store_warnings(path: Path) -> list[ClassifiedWarning]:
    payload = load_json(path)
    alerts = payload.get("alerts", []) if isinstance(payload, dict) else []
    if not isinstance(alerts, list):
        return []
    pending = 0
    unscorable = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        outcome = alert.get("outcome", {}) if isinstance(alert.get("outcome"), dict) else {}
        classification = str(outcome.get("classification") or outcome.get("status") or "").upper()
        if "UNSCORABLE" in classification:
            unscorable += 1
        elif "PENDING" in classification:
            pending += 1
    items: list[ClassifiedWarning] = []
    if pending:
        items.append(make_warning("Opportunity Alerts", f"PENDING_ALERTS:{pending}", evidence=str(path)))
    if unscorable:
        items.append(make_warning("Opportunity Alerts", f"UNSCORABLE_ALERTS:{unscorable}", evidence=str(path)))
    return items


def classified_capture_health_warnings() -> list[ClassifiedWarning]:
    snapshot = build_capture_health_snapshot()
    failure = snapshot.last_failed_capture
    if not failure.path:
        return []
    warning = f"CAPTURE_FAILURE:{failure.session}:{failure.error_message or failure.path}"
    return [make_warning("Capture Health", warning, evidence=str(failure.path))]


def make_warning(source: str, warning: str, *, evidence: str = "") -> ClassifiedWarning:
    category, severity, action = classify_warning(warning, source=source)
    return ClassifiedWarning(
        source=source,
        warning=warning,
        category=category,
        severity=severity,
        recommended_action=action,
        evidence=evidence,
    )


def recommended_next_actions(items: list[ClassifiedWarning]) -> list[str]:
    actions: list[str] = []
    for category in ("FAILED", "ACTIONABLE", "STALE", "MARKET_HOURS_REQUIRED", "UNKNOWN", "LEGACY_DATA_GAP"):
        matching = [item for item in items if item.category == category]
        if matching:
            actions.append(f"{category}: {matching[0].recommended_action}")
    if not actions:
        actions.append("No operational reliability action required beyond normal evidence collection.")
    return actions


def write_operational_reliability_report(
    payload: dict[str, Any],
    *,
    json_path: Path = OPERATIONAL_RELIABILITY_LATEST_JSON,
    markdown_path: Path = OPERATIONAL_RELIABILITY_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_operational_reliability_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_operational_reliability_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Operational Reliability Sprint v1 Final Report",
        "",
        payload.get("safety_note", ""),
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Total warnings classified: {payload.get('total_warnings', 0)}",
        f"- Actionable warning count: {payload.get('actionable_warning_count', 0)}",
        "",
        "## Category Counts",
        "",
        "| Category | Count |",
        "| --- | ---: |",
    ]
    for category, count in payload.get("category_counts", {}).items():
        lines.append(f"| {category} | {count} |")
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- {item}" for item in payload.get("next_actions", [])])
    lines.extend(
        [
            "",
            "## Classified Warnings",
            "",
            "| Source | Category | Severity | Warning | Action | Evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("warnings", []):
        lines.append(
            f"| {item.get('source', '')} | {item.get('category', '')} | {item.get('severity', '')} | "
            f"`{item.get('warning', '')}` | {item.get('recommended_action', '')} | `{item.get('evidence', '')}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def dedupe_warnings(items: list[ClassifiedWarning]) -> list[ClassifiedWarning]:
    seen: set[tuple[str, str, str]] = set()
    result: list[ClassifiedWarning] = []
    for item in items:
        key = (item.source, item.warning, item.evidence)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter operational reliability report.")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--json", type=Path, default=OPERATIONAL_RELIABILITY_LATEST_JSON)
    parser.add_argument("--md", type=Path, default=OPERATIONAL_RELIABILITY_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_operational_reliability_report(reports_dir=args.reports_dir, data_dir=args.data_dir)
    paths = write_operational_reliability_report(payload, json_path=args.json, markdown_path=args.md)
    print(
        json.dumps(
            {
                "overall_status": payload.get("overall_status"),
                "total_warnings": payload.get("total_warnings"),
                "category_counts": payload.get("category_counts"),
                "paths": {key: str(value) for key, value in paths.items()},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
