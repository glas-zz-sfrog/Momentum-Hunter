from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OpportunityAlert,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
    safe_stamp,
)
from momentum_hunter.time_utils import now_central


ALERT_PERFORMANCE_SCHEMA_VERSION = 1
ALERT_PERFORMANCE_ENGINE_VERSION = "alert_performance_analytics_v1"


@dataclass(frozen=True)
class AlertPerformanceRow:
    group_type: str
    group: str
    alert_count: int
    completed_count: int
    pending_count: int
    unscorable_count: int
    win_rate_pct: float | None
    average_5m_return_pct: float | None
    average_15m_return_pct: float | None
    average_30m_return_pct: float | None
    average_60m_return_pct: float | None
    average_return_pct: float | None
    average_mfe_pct: float | None
    average_mae_pct: float | None
    success_rate_pct: float | None
    failure_rate_pct: float | None
    noise_rate_pct: float | None
    late_rate_pct: float | None


@dataclass(frozen=True)
class AlertPerformanceReport:
    generated_at: str
    source_alerts_path: str
    total_alerts: int
    completed_alerts: int
    pending_alerts: int
    unscorable_alerts: int
    current_sample_size: int
    measurable_edge_status: str
    alert_type_performance: list[AlertPerformanceRow]
    symbol_performance: list[AlertPerformanceRow]
    readiness_state_performance: list[AlertPerformanceRow]
    best_alert_types: list[AlertPerformanceRow]
    worst_alert_types: list[AlertPerformanceRow]
    best_symbols: list[AlertPerformanceRow]
    worst_symbols: list[AlertPerformanceRow]
    warnings: list[str] = field(default_factory=list)


def build_alert_performance_report(
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    *,
    generated_at: str | None = None,
) -> AlertPerformanceReport:
    generated_at = generated_at or now_central().isoformat()
    alerts = load_alerts(alerts_path)
    completed = [alert for alert in alerts if is_completed_alert(alert)]
    pending = [alert for alert in alerts if is_pending_alert(alert)]
    unscorable = [alert for alert in alerts if is_unscorable_alert(alert)]
    alert_type_rows = summarize_alerts(alerts, group_type="alert_type", group_value=lambda alert: alert.alert_type)
    symbol_rows = summarize_alerts(alerts, group_type="symbol", group_value=lambda alert: alert.symbol)
    readiness_rows = summarize_alerts(alerts, group_type="readiness_state", group_value=lambda alert: alert.current_state)
    warnings: list[str] = []
    if not alerts:
        warnings.append("No opportunity alerts have been recorded yet.")
    if len(completed) < 20:
        warnings.append("SMALL SAMPLE SIZE: fewer than 20 completed alerts; diagnostic only.")
    if pending:
        warnings.append(f"{len(pending)} alert(s) are still pending and excluded from completed-return math.")
    if unscorable:
        warnings.append(f"{len(unscorable)} alert(s) are terminal data-quality outcomes and excluded from pending counts and performance math.")
    return AlertPerformanceReport(
        generated_at=generated_at,
        source_alerts_path=str(alerts_path),
        total_alerts=len(alerts),
        completed_alerts=len(completed),
        pending_alerts=len(pending),
        unscorable_alerts=len(unscorable),
        current_sample_size=len(completed),
        measurable_edge_status=measurable_edge_status(completed),
        alert_type_performance=alert_type_rows,
        symbol_performance=symbol_rows,
        readiness_state_performance=readiness_rows,
        best_alert_types=best_rows(alert_type_rows),
        worst_alert_types=worst_rows(alert_type_rows),
        best_symbols=best_rows(symbol_rows),
        worst_symbols=worst_rows(symbol_rows),
        warnings=warnings,
    )


def summarize_alerts(alerts: list[OpportunityAlert], *, group_type: str, group_value) -> list[AlertPerformanceRow]:
    by_group: dict[str, list[OpportunityAlert]] = {}
    for alert in alerts:
        group = str(group_value(alert) or "unknown")
        by_group.setdefault(group, []).append(alert)
    rows = [build_performance_row(group_type, group, items) for group, items in by_group.items()]
    return sorted(
        rows,
        key=lambda row: (row.completed_count, row.win_rate_pct or -1, row.average_60m_return_pct or -9999, row.group),
        reverse=True,
    )


def build_performance_row(group_type: str, group: str, alerts: list[OpportunityAlert]) -> AlertPerformanceRow:
    completed = [alert for alert in alerts if is_completed_alert(alert)]
    pending = [alert for alert in alerts if is_pending_alert(alert)]
    unscorable = [alert for alert in alerts if is_unscorable_alert(alert)]
    success_count = classification_count(completed, "SUCCESSFUL")
    failure_count = classification_count(completed, "FAILED")
    noise_count = classification_count(completed, "NOISE")
    late_count = classification_count(completed, "LATE")
    return AlertPerformanceRow(
        group_type=group_type,
        group=group,
        alert_count=len(alerts),
        completed_count=len(completed),
        pending_count=len(pending),
        unscorable_count=len(unscorable),
        win_rate_pct=percent(success_count, len(completed)),
        average_5m_return_pct=average([alert.outcome.five_minute_return_pct for alert in completed]),
        average_15m_return_pct=average([alert.outcome.fifteen_minute_return_pct for alert in completed]),
        average_30m_return_pct=average([alert.outcome.thirty_minute_return_pct for alert in completed]),
        average_60m_return_pct=average([alert.outcome.sixty_minute_return_pct for alert in completed]),
        average_return_pct=average([best_available_return(alert) for alert in completed]),
        average_mfe_pct=average([best_available_mfe(alert) for alert in completed]),
        average_mae_pct=average([best_available_mae(alert) for alert in completed]),
        success_rate_pct=percent(success_count, len(completed)),
        failure_rate_pct=percent(failure_count, len(completed)),
        noise_rate_pct=percent(noise_count, len(completed)),
        late_rate_pct=percent(late_count, len(completed)),
    )


def export_alert_performance_report(report: AlertPerformanceReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"alert-performance-report-{safe_stamp(report.generated_at)}"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_alert_performance_json(report, json_path)
    write_alert_performance_markdown(report, md_path)
    return {"json": json_path, "report": md_path}


def write_alert_performance_json(report: AlertPerformanceReport, path: Path) -> None:
    payload = {
        "schema_version": ALERT_PERFORMANCE_SCHEMA_VERSION,
        "engine_version": ALERT_PERFORMANCE_ENGINE_VERSION,
        "generated_at": report.generated_at,
        "source_alerts_path": report.source_alerts_path,
        "total_alerts": report.total_alerts,
        "completed_alerts": report.completed_alerts,
        "pending_alerts": report.pending_alerts,
        "unscorable_alerts": report.unscorable_alerts,
        "current_sample_size": report.current_sample_size,
        "measurable_edge_status": report.measurable_edge_status,
        "warnings": report.warnings,
        "alert_type_performance": [asdict(row) for row in report.alert_type_performance],
        "symbol_performance": [asdict(row) for row in report.symbol_performance],
        "readiness_state_performance": [asdict(row) for row in report.readiness_state_performance],
        "best_alert_types": [asdict(row) for row in report.best_alert_types],
        "worst_alert_types": [asdict(row) for row in report.worst_alert_types],
        "best_symbols": [asdict(row) for row in report.best_symbols],
        "worst_symbols": [asdict(row) for row in report.worst_symbols],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_alert_performance_markdown(report: AlertPerformanceReport, path: Path) -> None:
    lines = [
        f"# Momentum Hunter Alert Performance - {report.generated_at}",
        "",
        "Research-only alert analytics. This report reads existing alert outcomes and does not modify trading rules.",
        "",
        "## Current Sample Size",
        "",
        f"- Total alerts: {report.total_alerts}",
        f"- Completed alerts: {report.completed_alerts}",
        f"- Pending alerts: {report.pending_alerts}",
        f"- Unscorable alerts: {report.unscorable_alerts}",
        f"- Measurable edge status: {report.measurable_edge_status}",
        "",
        "## Best Alert Types",
        "",
    ]
    lines.extend(performance_table_lines(report.best_alert_types, empty="No completed alert types yet."))
    lines.extend(["", "## Worst Alert Types", ""])
    lines.extend(performance_table_lines(report.worst_alert_types, empty="No completed alert types yet."))
    lines.extend(["", "## Best Symbols", ""])
    lines.extend(performance_table_lines(report.best_symbols, empty="No completed symbol outcomes yet."))
    lines.extend(["", "## Worst Symbols", ""])
    lines.extend(performance_table_lines(report.worst_symbols, empty="No completed symbol outcomes yet."))
    lines.extend(["", "## Alert Type Performance", ""])
    lines.extend(performance_table_lines(report.alert_type_performance, empty="No alert types recorded yet."))
    lines.extend(["", "## Symbol Performance", ""])
    lines.extend(performance_table_lines(report.symbol_performance, empty="No symbols recorded yet."))
    lines.extend(["", "## Readiness State Performance", ""])
    lines.extend(performance_table_lines(report.readiness_state_performance, empty="No readiness states recorded yet."))
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in report.warnings] if report.warnings else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def performance_table_lines(rows: list[AlertPerformanceRow], *, empty: str) -> list[str]:
    if not rows:
        return [f"- {empty}", ""]
    lines = [
        "| Group | Alerts | Completed | Pending | Unscorable | Win % | Avg 5m | Avg 15m | Avg 30m | Avg 60m | Avg MFE | Avg MAE | Success % | Failure % | Noise % | Late % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.group} | {row.alert_count} | {row.completed_count} | {row.pending_count} | {row.unscorable_count} | "
            f"{format_value(row.win_rate_pct)} | {format_value(row.average_5m_return_pct)} | "
            f"{format_value(row.average_15m_return_pct)} | {format_value(row.average_30m_return_pct)} | "
            f"{format_value(row.average_60m_return_pct)} | {format_value(row.average_mfe_pct)} | "
            f"{format_value(row.average_mae_pct)} | {format_value(row.success_rate_pct)} | "
            f"{format_value(row.failure_rate_pct)} | {format_value(row.noise_rate_pct)} | {format_value(row.late_rate_pct)} |"
        )
    lines.append("")
    return lines


def best_rows(rows: list[AlertPerformanceRow]) -> list[AlertPerformanceRow]:
    completed = [row for row in rows if row.completed_count]
    return sorted(
        completed,
        key=lambda row: (row.win_rate_pct or 0, row.average_60m_return_pct or -9999, row.average_mfe_pct or -9999, row.completed_count),
        reverse=True,
    )[:10]


def worst_rows(rows: list[AlertPerformanceRow]) -> list[AlertPerformanceRow]:
    completed = [row for row in rows if row.completed_count]
    return sorted(
        completed,
        key=lambda row: (
            row.win_rate_pct if row.win_rate_pct is not None else 9999,
            row.average_60m_return_pct if row.average_60m_return_pct is not None else 9999,
            -(row.noise_rate_pct or 0),
            row.group,
        ),
    )[:10]


def measurable_edge_status(completed: list[OpportunityAlert]) -> str:
    if len(completed) < 20:
        return "INSUFFICIENT_SAMPLE"
    wins = classification_count(completed, "SUCCESSFUL")
    win_rate = percent(wins, len(completed)) or 0
    avg_return = average([best_available_return(alert) for alert in completed]) or 0
    if win_rate >= 55 and avg_return > 0:
        return "POSITIVE_EVIDENCE"
    if win_rate <= 40 or avg_return < 0:
        return "NEGATIVE_EVIDENCE"
    return "MIXED_EVIDENCE"


def classification_count(alerts: list[OpportunityAlert], classification: str) -> int:
    return sum(1 for alert in alerts if alert.outcome.classification == classification)


def best_available_return(alert: OpportunityAlert) -> float | None:
    return first_not_none(
        alert.outcome.sixty_minute_return_pct,
        alert.outcome.thirty_minute_return_pct,
        alert.outcome.fifteen_minute_return_pct,
        alert.outcome.five_minute_return_pct,
    )


def best_available_mfe(alert: OpportunityAlert) -> float | None:
    return first_not_none(alert.outcome.mfe_60m_pct, alert.outcome.mfe_30m_pct, alert.outcome.mfe_15m_pct)


def best_available_mae(alert: OpportunityAlert) -> float | None:
    return first_not_none(alert.outcome.mae_60m_pct, alert.outcome.mae_30m_pct, alert.outcome.mae_15m_pct)


def first_not_none(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(mean(clean), 2)


def percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def format_value(value: float | int | None) -> str:
    return "n/a" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter alert performance analytics.")
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    report = build_alert_performance_report(args.alerts_path)
    paths = export_alert_performance_report(report, output_dir=args.output_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
