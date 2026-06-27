from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from momentum_hunter.alert_performance import AlertPerformanceRow, build_alert_performance_report
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.evidence_health import build_evidence_health_report
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.time_utils import now_central


ENGINE_VERSION = "evidence_analytics_maturity_v1"
REPORTS_DIR = DATA_DIR / "reports"
EVIDENCE_ANALYTICS_MATURITY_LATEST_JSON = REPORTS_DIR / "evidence-analytics-maturity-latest.json"
EVIDENCE_ANALYTICS_MATURITY_LATEST_MD = REPORTS_DIR / "evidence-analytics-maturity-latest.md"
GROUP_COMPLETED_THRESHOLD = 10
OVERALL_GATES = [
    {
        "name": "Collect Evidence",
        "required_completed_alerts": 0,
        "allowed_action": "Collect evidence only",
        "strategy_change_allowed": False,
    },
    {
        "name": "Identify Patterns",
        "required_completed_alerts": 25,
        "allowed_action": "Identify patterns",
        "strategy_change_allowed": False,
    },
    {
        "name": "Recommend Investigations",
        "required_completed_alerts": 50,
        "allowed_action": "Recommend investigations",
        "strategy_change_allowed": False,
    },
    {
        "name": "Strategy Modification Review",
        "required_completed_alerts": 100,
        "allowed_action": "Review possible strategy modifications",
        "strategy_change_allowed": False,
    },
]


def build_evidence_analytics_maturity_report(
    *,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central().isoformat()
    performance = build_alert_performance_report(alerts_path, generated_at=generated_at)
    health = build_evidence_health_report(alerts_path=alerts_path)
    gate = health.evidence_gate
    completed = performance.completed_alerts
    next_gate = next_locked_gate(completed)
    alert_type_groups = group_maturity_rows(performance.alert_type_performance, group_type="alert_type")
    symbol_groups = group_maturity_rows(performance.symbol_performance, group_type="symbol")
    readiness_groups = group_maturity_rows(performance.readiness_state_performance, group_type="readiness_state")
    warnings = maturity_warnings(performance, health, alert_type_groups, symbol_groups, readiness_groups)
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at,
        "source_alerts_path": str(alerts_path),
        "overall_status": "WARN" if warnings else "PASS",
        "total_alerts": performance.total_alerts,
        "completed_alerts": performance.completed_alerts,
        "pending_alerts": performance.pending_alerts,
        "unscorable_alerts": performance.unscorable_alerts,
        "success_count": health.success_count,
        "failure_count": health.failure_count,
        "noise_count": health.noise_count,
        "late_count": health.late_count,
        "completion_rate_pct": health.completion_rate_pct,
        "measurable_edge_status": performance.measurable_edge_status,
        "evidence_gate": asdict(gate),
        "overall_gates": gate_rows(completed),
        "next_locked_gate": next_gate,
        "evidence_needed_to_next_gate": max(0, int(next_gate["required_completed_alerts"]) - completed) if next_gate else 0,
        "strategy_optimization_status": gate.strategy_optimization_status,
        "strategy_change_recommendations_allowed": False,
        "sample_confidence": sample_confidence(completed),
        "alert_type_maturity": alert_type_groups,
        "symbol_maturity": symbol_groups,
        "readiness_state_maturity": readiness_groups,
        "insufficient_alert_types": [row for row in alert_type_groups if row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW"],
        "insufficient_symbols": [row for row in symbol_groups if row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW"],
        "insufficient_readiness_states": [row for row in readiness_groups if row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW"],
        "data_quality_gaps": {
            "pending_alerts": performance.pending_alerts,
            "unscorable_alerts": performance.unscorable_alerts,
            "stale_pending_alerts": len(health.stale_pending_alerts),
            "missing_minute_bar_alerts": len(health.missing_minute_bar_alerts),
            "missing_outcome_alerts": len(health.missing_outcome_alerts),
            "incomplete_outcome_alerts": len(health.incomplete_outcome_alerts),
            "missing_readiness_state_alerts": len(health.missing_readiness_state_alerts),
            "missing_news_snapshot_alerts": len(health.missing_news_snapshot_alerts),
        },
        "can_answer": {
            "are_alerts_predictive": can_answer_predictive(completed),
            "which_alert_types_work": can_answer_groups(alert_type_groups),
            "which_symbols_work": can_answer_groups(symbol_groups),
            "which_readiness_states_work": can_answer_groups(readiness_groups),
            "does_system_have_edge": can_answer_edge(completed, performance.measurable_edge_status),
        },
        "warnings": warnings,
        "safety_notes": [
            "Report-only analysis; no scoring, readiness, alert, outcome, or trade-planning logic changed.",
            "Pending and unscorable alerts are not counted as completed outcomes.",
            "Strategy changes remain locked until evidence thresholds are met and reviewed by Steven.",
        ],
    }


def write_evidence_analytics_maturity_report(
    payload: dict[str, Any],
    *,
    json_path: Path = EVIDENCE_ANALYTICS_MATURITY_LATEST_JSON,
    markdown_path: Path = EVIDENCE_ANALYTICS_MATURITY_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def group_maturity_rows(rows: list[AlertPerformanceRow], *, group_type: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        completed = row.completed_count
        result.append(
            {
                "group_type": group_type,
                "group": row.group,
                "alert_count": row.alert_count,
                "completed_count": completed,
                "pending_count": row.pending_count,
                "unscorable_count": row.unscorable_count,
                "sample_status": "SUFFICIENT_FOR_PATTERN_REVIEW"
                if completed >= GROUP_COMPLETED_THRESHOLD
                else "INSUFFICIENT_GROUP_SAMPLE",
                "completed_needed": max(0, GROUP_COMPLETED_THRESHOLD - completed),
                "win_rate_pct": row.win_rate_pct,
                "average_60m_return_pct": row.average_60m_return_pct,
                "average_mfe_pct": row.average_mfe_pct,
                "average_mae_pct": row.average_mae_pct,
            }
        )
    return result


def gate_rows(completed_alerts: int) -> list[dict[str, Any]]:
    rows = []
    for gate in OVERALL_GATES:
        required = int(gate["required_completed_alerts"])
        unlocked = completed_alerts >= required
        rows.append(
            {
                **gate,
                "status": "UNLOCKED" if unlocked else "LOCKED",
                "current_completed_alerts": completed_alerts,
                "completed_needed": max(0, required - completed_alerts),
            }
        )
    return rows


def next_locked_gate(completed_alerts: int) -> dict[str, Any] | None:
    locked = [row for row in gate_rows(completed_alerts) if row["status"] == "LOCKED"]
    return locked[0] if locked else None


def sample_confidence(completed_alerts: int) -> str:
    if completed_alerts < 25:
        return "COLLECTING_ONLY"
    if completed_alerts < 50:
        return "EARLY_PATTERN_REVIEW"
    if completed_alerts < 100:
        return "INVESTIGATION_READY"
    return "STRATEGY_REVIEW_READY"


def maturity_warnings(
    performance,
    health,
    alert_type_groups: list[dict[str, Any]],
    symbol_groups: list[dict[str, Any]],
    readiness_groups: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    if performance.completed_alerts < 25:
        warnings.append("INSUFFICIENT_COMPLETED_ALERTS_FOR_PATTERN_REVIEW")
    if performance.completed_alerts < 100:
        warnings.append("STRATEGY_CHANGES_LOCKED")
    if performance.pending_alerts:
        warnings.append(f"PENDING_ALERTS:{performance.pending_alerts}")
    if performance.unscorable_alerts:
        warnings.append(f"UNSCORABLE_ALERTS:{performance.unscorable_alerts}")
    if health.missing_minute_bar_alerts:
        warnings.append(f"MISSING_MINUTE_BARS:{len(health.missing_minute_bar_alerts)}")
    if all(row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW" for row in alert_type_groups):
        warnings.append("NO_ALERT_TYPE_HAS_SUFFICIENT_SAMPLE")
    if all(row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW" for row in symbol_groups):
        warnings.append("NO_SYMBOL_HAS_SUFFICIENT_SAMPLE")
    if all(row["sample_status"] != "SUFFICIENT_FOR_PATTERN_REVIEW" for row in readiness_groups):
        warnings.append("NO_READINESS_STATE_HAS_SUFFICIENT_SAMPLE")
    return warnings


def can_answer_predictive(completed_alerts: int) -> str:
    return "NOT_YET: collect at least 25 completed alerts." if completed_alerts < 25 else "PARTIAL: enough for early pattern review."


def can_answer_groups(rows: list[dict[str, Any]]) -> str:
    sufficient = [row for row in rows if row["sample_status"] == "SUFFICIENT_FOR_PATTERN_REVIEW"]
    if not sufficient:
        return f"NOT_YET: no group has {GROUP_COMPLETED_THRESHOLD} completed outcomes."
    return f"PARTIAL: {len(sufficient)} group(s) have enough completed outcomes for pattern review."


def can_answer_edge(completed_alerts: int, edge_status: str) -> str:
    if completed_alerts < 100:
        return f"NOT_YET: {completed_alerts}/100 completed alerts; current status {edge_status}."
    return f"REVIEW_READY: 100+ completed alerts; current status {edge_status}."


def format_markdown(payload: dict[str, Any]) -> str:
    gate = payload.get("evidence_gate", {})
    lines = [
        "# Evidence Analytics Maturity v1",
        "",
        "Research-only maturity report. This does not change signal generation, scoring, readiness, or trade planning.",
        "",
        "## Summary",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Total alerts: {payload.get('total_alerts', 0)}",
        f"- Completed alerts: {payload.get('completed_alerts', 0)}",
        f"- Pending alerts: {payload.get('pending_alerts', 0)}",
        f"- Unscorable alerts: {payload.get('unscorable_alerts', 0)}",
        f"- Sample confidence: `{payload.get('sample_confidence', '')}`",
        f"- Evidence status: `{gate.get('evidence_status', '')}`",
        f"- Allowed action: `{gate.get('allowed_action', '')}`",
        f"- Strategy optimization: `{payload.get('strategy_optimization_status', '')}`",
        "",
        "## Gates",
        "",
        "| Gate | Status | Completed | Required | Needed | Allowed Action |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in payload.get("overall_gates", []):
        lines.append(
            f"| {row.get('name', '')} | {row.get('status', '')} | {row.get('current_completed_alerts', 0)} | "
            f"{row.get('required_completed_alerts', 0)} | {row.get('completed_needed', 0)} | {row.get('allowed_action', '')} |"
        )
    lines.extend(
        [
            "",
            "## Current Answers",
            "",
        ]
    )
    for question, answer in payload.get("can_answer", {}).items():
        lines.append(f"- {question}: {answer}")
    lines.extend(["", "## Alert Type Maturity", ""])
    lines.extend(group_table(payload.get("alert_type_maturity", []), empty="No alert types recorded."))
    lines.extend(["", "## Symbol Maturity", ""])
    lines.extend(group_table(payload.get("symbol_maturity", []), empty="No symbols recorded."))
    lines.extend(["", "## Data Quality Gaps", ""])
    for key, value in payload.get("data_quality_gaps", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings", [])
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    lines.extend(["", "## Safety Notes", ""])
    lines.extend(f"- {note}" for note in payload.get("safety_notes", []))
    return "\n".join(lines) + "\n"


def group_table(rows: list[dict[str, Any]], *, empty: str) -> list[str]:
    if not rows:
        return [f"- {empty}"]
    lines = [
        "| Group | Alerts | Completed | Needed | Status | Win % | Avg 60m | Avg MFE | Avg MAE |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:20]:
        lines.append(
            f"| {row.get('group', '')} | {row.get('alert_count', 0)} | {row.get('completed_count', 0)} | "
            f"{row.get('completed_needed', 0)} | {row.get('sample_status', '')} | "
            f"{format_value(row.get('win_rate_pct'))} | {format_value(row.get('average_60m_return_pct'))} | "
            f"{format_value(row.get('average_mfe_pct'))} | {format_value(row.get('average_mae_pct'))} |"
        )
    return lines


def format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Evidence Analytics Maturity report.")
    parser.add_argument("--alerts", type=Path, default=OPPORTUNITY_ALERTS_PATH, help="Opportunity alerts JSON path.")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Directory for generated reports.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_evidence_analytics_maturity_report(alerts_path=args.alerts)
    write_evidence_analytics_maturity_report(
        payload,
        json_path=args.output_dir / EVIDENCE_ANALYTICS_MATURITY_LATEST_JSON.name,
        markdown_path=args.output_dir / EVIDENCE_ANALYTICS_MATURITY_LATEST_MD.name,
    )
    print(
        json.dumps(
            {
                "overall_status": payload["overall_status"],
                "completed_alerts": payload["completed_alerts"],
                "sample_confidence": payload["sample_confidence"],
                "warnings": payload["warnings"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
