from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH, load_active_monitor_status
from momentum_hunter.config import DATA_DIR
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH


WORKSTATION_SNAPSHOT_SCHEMA_VERSION = 2
READ_ONLY_MODE_LABEL = "READ_ONLY_PERSISTED_EVIDENCE"
ACTIVE_ALERT_STATUSES = frozenset({"PENDING_OUTCOME", "ACTIVE"})
ALERT_ROW_LIMIT = 50
OUTCOME_ROW_LIMIT = 100


@dataclass(frozen=True)
class WorkstationReadModelPaths:
    data_dir: Path
    reports_dir: Path
    monitor_status_path: Path
    alerts_path: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path = DATA_DIR) -> "WorkstationReadModelPaths":
        return cls(
            data_dir=data_dir,
            reports_dir=data_dir / "reports",
            monitor_status_path=data_dir / ACTIVE_MONITOR_STATUS_PATH.name,
            alerts_path=data_dir / OPPORTUNITY_ALERTS_PATH.name,
        )


def build_read_only_workspace_snapshot(
    *,
    paths: WorkstationReadModelPaths | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a wire-safe, read-only view of persisted Momentum Hunter evidence.

    This mapper deliberately reads precomputed reports and status files only. It does not
    rescore candidates, recalculate readiness, select replay identities, call providers,
    or write any source artifact.
    """

    paths = paths or WorkstationReadModelPaths.from_data_dir()
    observed_at = as_utc(observed_at or datetime.now(timezone.utc))
    report_path = latest_trade_report_path(paths.reports_dir)
    report_payload = load_json_object(report_path) if report_path else None
    report_metadata = object_value(report_payload, "metadata")
    report_observed_at = parse_timestamp(str(report_metadata.get("generated_at", "")), observed_at)

    candidates: list[dict[str, Any]] = []
    activity: list[dict[str, Any]] = []
    health_components: list[dict[str, Any]] = []
    if report_path is None:
        report_summary = "No persisted trade-planning report is available. Candidate data is unavailable; no fallback data was created."
        health_components.append(health_component("Trade planning report", "Unavailable", report_summary, observed_at))
        activity.append(activity_event(observed_at, "Research", report_summary, "", "Unavailable"))
    elif report_payload is None:
        report_summary = f"The persisted trade-planning report '{report_path.name}' could not be read. Candidate data is unavailable."
        health_components.append(health_component("Trade planning report", "Unavailable", report_summary, observed_at))
        activity.append(activity_event(observed_at, "Research", report_summary, "", "Unavailable"))
    else:
        source_rows = list_value(report_payload, "candidates")
        candidates = [
            candidate_snapshot(item, report_path=report_path, observed_at=report_observed_at)
            for item in source_rows
            if isinstance(item, dict) and str(item.get("symbol", "")).strip()
        ]
        report_summary = (
            f"Read-only persisted trade-planning report '{report_path.name}' loaded with {len(candidates)} candidate(s). "
            "Scores and readiness labels are displayed from the source report without recalculation."
        )
        health_components.append(health_component("Trade planning report", "Healthy", report_summary, report_observed_at))
        activity.append(activity_event(report_observed_at, "Research", report_summary, "", "Healthy"))

    monitor_status = load_active_monitor_status(paths.monitor_status_path)
    if monitor_status is None:
        monitor_summary = "No active-monitor status file is available. Collection state is unavailable."
        health_components.append(health_component("Active monitor", "Unavailable", monitor_summary, observed_at))
        activity.append(activity_event(observed_at, "Monitoring", monitor_summary, "", "Unavailable"))
    else:
        monitor_checked_at = parse_timestamp(monitor_status.updated_at or monitor_status.started_at, observed_at)
        monitor_state = monitor_health_state(monitor_status.state)
        monitor_summary = (
            f"Active monitor {monitor_status.state or 'UNKNOWN'}: "
            f"{monitor_status.cycles_completed}/{monitor_status.cycles_requested} cycle(s) completed."
        )
        if monitor_status.last_error:
            monitor_summary = f"{monitor_summary} Last error: {monitor_status.last_error}"
        if monitor_status.warnings:
            monitor_summary = f"{monitor_summary} Warnings: {'; '.join(monitor_status.warnings[:2])}"
        health_components.append(health_component("Active monitor", monitor_state, monitor_summary, monitor_checked_at))
        activity.append(activity_event(monitor_checked_at, "Monitoring", monitor_summary, "", monitor_state))

    alerts_payload = load_json_object(paths.alerts_path)
    if alerts_payload is None:
        alerts_summary = "No readable opportunity-alert store is available. Evidence alert counts are unavailable."
        alert_evidence = unavailable_alert_evidence(alerts_summary, observed_at)
        health_components.append(health_component("Evidence alerts", "Unavailable", alerts_summary, observed_at))
        activity.append(activity_event(observed_at, "Evidence", alerts_summary, "", "Unavailable"))
    elif not isinstance(alerts_payload.get("alerts"), list) or any(
        not isinstance(item, dict) for item in alerts_payload["alerts"]
    ):
        alerts_checked_at = file_timestamp(paths.alerts_path, observed_at)
        alerts_summary = (
            "The opportunity-alert store is readable, but its alerts collection is structurally invalid. "
            "Evidence alert counts and rows are unavailable."
        )
        alert_evidence = unavailable_alert_evidence(alerts_summary, alerts_checked_at)
        health_components.append(health_component("Evidence alerts", "Unavailable", alerts_summary, alerts_checked_at))
        activity.append(activity_event(alerts_checked_at, "Evidence", alerts_summary, "", "Unavailable"))
    else:
        alerts = alerts_payload["alerts"]
        active_alerts = [
            alert
            for alert in alerts
            if alert_outcome_status(alert) in ACTIVE_ALERT_STATUSES
        ]
        alerts_summary = f"Read-only alert store contains {len(alerts)} alert(s), including {len(active_alerts)} active or pending outcome(s)."
        alerts_checked_at = file_timestamp(paths.alerts_path, observed_at)
        alert_evidence = build_alert_evidence_snapshot(alerts, alerts_checked_at)
        health_components.append(health_component("Evidence alerts", "Healthy", alerts_summary, alerts_checked_at))
        activity.append(activity_event(alerts_checked_at, "Evidence", alerts_summary, "", "Healthy"))

    replay = replay_snapshot(report_metadata, report_path, report_observed_at)
    replay_health = "Healthy" if report_payload is not None else "Unavailable"
    health_components.append(health_component("Replay context", replay_health, replay["summary"], report_observed_at))

    snapshot_summary = (
        "Read-only Python evidence snapshot. Trade planning, risk, chart data, simulation, broker, paper, and live workflows remain unavailable at this boundary."
    )
    return {
        "schemaVersion": WORKSTATION_SNAPSHOT_SCHEMA_VERSION,
        "mode": READ_ONLY_MODE_LABEL,
        "observedAt": timestamp_text(observed_at),
        "summary": snapshot_summary,
        "candidates": candidates,
        "activity": activity,
        "health": {
            "checkedAt": timestamp_text(observed_at),
            "components": health_components,
        },
        "alertEvidence": alert_evidence,
        "replay": replay,
        "planningAvailable": False,
    }


def candidate_snapshot(row: dict[str, Any], *, report_path: Path, observed_at: datetime) -> dict[str, Any]:
    market_data = object_value(row, "market_data")
    scoring = object_value(row, "scoring")
    trade_plan = object_value(row, "trade_plan")
    readiness = str(trade_plan.get("readiness", "UNAVAILABLE")).strip() or "UNAVAILABLE"
    last_price = number_or_none(market_data.get("last_price"))
    relative_volume = number_or_none(market_data.get("relative_volume"))
    liquidity = liquidity_summary(market_data)
    quality_parts = ["Persisted report"]
    if last_price is None:
        quality_parts.append("last price unavailable")
    if relative_volume is None:
        quality_parts.append("relative volume unavailable")
    if readiness == "UNAVAILABLE":
        quality_parts.append("readiness unavailable")
    catalyst = str(scoring.get("catalyst_summary", "")).strip() or "No stored catalyst summary"
    lineage = {
        "sourceLabel": "Persisted trade-planning report",
        "asOf": timestamp_text(observed_at),
        "summary": f"Read-only source: {report_path.name}. No score or readiness recalculation occurred.",
    }
    return {
        "symbol": str(row.get("symbol", "")).strip().upper(),
        "company": str(row.get("company", "")).strip() or "Company unavailable",
        "lastPrice": last_price,
        "changePercent": number_or_none(market_data.get("premarket_percent")),
        "volume": integer_or_none(market_data.get("intraday_volume")) or integer_or_none(market_data.get("premarket_volume")),
        "relativeVolume": relative_volume,
        "catalyst": catalyst,
        "sourceReadinessLabel": readiness,
        "qualityLabel": "; ".join(quality_parts),
        "observedAt": timestamp_text(observed_at),
        "score": integer_or_none(scoring.get("composite_score")) or 0,
        "liquidity": liquidity,
        "catalystSummary": {
            "headline": catalyst,
            "sourceLabel": "Persisted trade-planning report",
            "observedAt": timestamp_text(observed_at),
        },
        "dataLineage": lineage,
        "notes": [str(note) for note in list_value(row, "opportunity_notes") if str(note).strip()],
    }


def replay_snapshot(metadata: dict[str, Any], report_path: Path | None, observed_at: datetime) -> dict[str, Any]:
    if report_path is None:
        return {
            "replayId": "UNAVAILABLE",
            "asOf": timestamp_text(observed_at),
            "symbol": "",
            "interval": "source capture",
            "summary": "Replay context is unavailable because no persisted source report is available.",
        }
    source_capture_path = str(metadata.get("source_capture_path", "")).strip()
    source_capture_time = str(metadata.get("source_capture_time", "")).strip()
    return {
        "replayId": "NOT_SELECTED",
        "asOf": timestamp_text(parse_timestamp(source_capture_time, observed_at)),
        "symbol": "",
        "interval": "source capture",
        "summary": (
            f"Replay remains read-only. Source capture: {Path(source_capture_path).name if source_capture_path else 'not recorded'}. "
            "No candidate replay identity was synthesized by the workstation boundary."
        ),
    }


def health_component(name: str, state: str, summary: str, checked_at: datetime) -> dict[str, Any]:
    return {"name": name, "state": state, "summary": summary, "checkedAt": timestamp_text(checked_at)}


def activity_event(timestamp: datetime, category: str, message: str, symbol: str, state: str) -> dict[str, Any]:
    return {
        "timestamp": timestamp_text(timestamp),
        "category": category,
        "message": message,
        "symbol": symbol,
        "state": state,
    }


def unavailable_alert_evidence(summary: str, observed_at: datetime) -> dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "asOf": timestamp_text(observed_at),
        "summary": summary,
        "totalAlertCount": 0,
        "activeAlertCount": 0,
        "recordedOutcomeCount": 0,
        "unscorableOutcomeCount": 0,
        "activeAlerts": [],
        "outcomes": [],
    }


def build_alert_evidence_snapshot(alerts: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
    ordered = sorted(alerts, key=alert_timestamp_sort_key, reverse=True)
    active = [item for item in ordered if alert_outcome_status(item) in ACTIVE_ALERT_STATUSES]
    outcomes = [item for item in ordered if alert_outcome_status(item) not in ACTIVE_ALERT_STATUSES]
    unscorable_count = sum(
        1
        for item in outcomes
        if alert_outcome_status(item) == "UNSCORABLE_OUTCOME"
        or str(object_value(item, "outcome").get("classification", "")).strip().upper().startswith("UNSCORABLE")
    )
    if not alerts:
        state = "EMPTY"
        summary = (
            "The persisted opportunity-alert store is readable but contains no alerts. "
            "Outcome evidence is insufficient; no analytics or classifications were inferred."
        )
    else:
        state = "AVAILABLE"
        summary = (
            f"Persisted alert evidence: {len(alerts)} total, {len(active)} active or pending, "
            f"{len(outcomes)} recorded outcome(s), {unscorable_count} unscorable. "
            f"Stored alert states and outcome classifications are displayed without recalculation. "
            f"Counts cover the full store; row detail is limited to the newest {ALERT_ROW_LIMIT} active alerts "
            f"and {OUTCOME_ROW_LIMIT} outcomes."
        )
    return {
        "state": state,
        "asOf": timestamp_text(as_of),
        "summary": summary,
        "totalAlertCount": len(alerts),
        "activeAlertCount": len(active),
        "recordedOutcomeCount": len(outcomes),
        "unscorableOutcomeCount": unscorable_count,
        "activeAlerts": [alert_event_snapshot(item) for item in active[:ALERT_ROW_LIMIT]],
        "outcomes": [alert_outcome_snapshot(item) for item in outcomes[:OUTCOME_ROW_LIMIT]],
    }


def alert_event_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    outcome = object_value(item, "outcome")
    return {
        "alertId": str(item.get("alert_id", "")).strip(),
        "timestamp": optional_timestamp_text(item.get("timestamp")),
        "symbol": str(item.get("symbol", "")).strip().upper(),
        "alertType": str(item.get("alert_type", "")).strip(),
        "state": str(item.get("current_state", "")).strip() or str(outcome.get("status", "")).strip() or "UNAVAILABLE",
        "summary": str(item.get("reason", "")).strip() or "No alert reason was recorded.",
    }


def alert_outcome_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    outcome = object_value(item, "outcome")
    status = str(outcome.get("status", "")).strip() or "UNAVAILABLE"
    classification = str(outcome.get("classification", "")).strip() or "UNAVAILABLE"
    return {
        "alertId": str(item.get("alert_id", "")).strip(),
        "symbol": str(item.get("symbol", "")).strip().upper(),
        "alertTimestamp": optional_timestamp_text(item.get("timestamp")),
        "status": status,
        "classification": classification,
        "summary": stored_outcome_summary(outcome, status=status, classification=classification),
    }


def alert_outcome_status(item: dict[str, Any]) -> str:
    return str(object_value(item, "outcome").get("status", "PENDING_OUTCOME")).strip().upper() or "PENDING_OUTCOME"


def alert_timestamp_sort_key(item: dict[str, Any]) -> tuple[bool, str]:
    timestamp = optional_timestamp_text(item.get("timestamp"))
    return timestamp is not None, timestamp or ""


def stored_outcome_summary(outcome: dict[str, Any], *, status: str, classification: str) -> str:
    details = [f"Stored status {status}", f"classification {classification}"]
    for key, label in (
        ("five_minute_return_pct", "5m"),
        ("fifteen_minute_return_pct", "15m"),
        ("thirty_minute_return_pct", "30m"),
        ("sixty_minute_return_pct", "60m"),
        ("mfe_30m_pct", "MFE 30m"),
        ("mae_30m_pct", "MAE 30m"),
    ):
        value = number_or_none(outcome.get(key))
        if value is not None:
            details.append(f"{label} {value:+.2f}%")
    for key, label in (
        ("target_1_hit", "target 1"),
        ("target_2_hit", "target 2"),
        ("stop_hit", "stop"),
    ):
        value = outcome.get(key)
        if isinstance(value, bool):
            details.append(f"{label} {'hit' if value else 'not hit'}")
    return "; ".join(details) + "."


def optional_timestamp_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return timestamp_text(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def load_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def object_value(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = payload.get(key) if payload else None
    return value if isinstance(value, dict) else {}


def list_value(payload: dict[str, Any] | None, key: str) -> list[Any]:
    value = payload.get(key) if payload else None
    return value if isinstance(value, list) else []


def number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer_or_none(value: object) -> int | None:
    numeric = number_or_none(value)
    return int(numeric) if numeric is not None else None


def liquidity_summary(market_data: dict[str, Any]) -> str:
    details: list[str] = []
    relative_volume = number_or_none(market_data.get("relative_volume"))
    spread_percent = number_or_none(market_data.get("spread_percent"))
    if relative_volume is not None:
        details.append(f"RVOL {relative_volume:.2f}x")
    if spread_percent is not None:
        details.append(f"spread {spread_percent:.2f}%")
    return " | ".join(details) or "Liquidity data unavailable"


def monitor_health_state(state: str) -> str:
    normalized = state.strip().upper()
    if normalized in {"FAILED", "BLOCKED"}:
        return "Degraded"
    if normalized in {"", "UNKNOWN"}:
        return "Unavailable"
    return "Healthy"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: str, fallback: datetime) -> datetime:
    if not value.strip():
        return fallback
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return fallback


def file_timestamp(path: Path, fallback: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return fallback


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")
