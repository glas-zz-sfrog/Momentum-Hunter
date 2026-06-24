from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.entry_plans import EntryPlan, load_entry_plans
from momentum_hunter.review import ReviewDecision, ReviewStatus, load_review_decisions
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import EXECUTION_READY_PREMARKET, EXECUTION_READY_TRADE


MONITOR_SYMBOLS_PATH = DATA_DIR / "opportunity-monitor-symbols.json"
REPORT_SCHEMA_VERSION = 1
TARGET_SOURCES = {
    "execution_ready": 100,
    "watchlist": 80,
    "entry_plan": 70,
    "interested": 60,
    "user_defined": 50,
}


@dataclass(frozen=True)
class UserDefinedMonitorSymbol:
    symbol: str
    notes: str = ""
    enabled: bool = True
    added_at: str = ""


@dataclass
class MonitorTarget:
    symbol: str
    sources: list[str] = field(default_factory=list)
    review_statuses: list[str] = field(default_factory=list)
    entry_plan_status: str = ""
    execution_state: str = ""
    latest_trade_report: str = ""
    notes: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass(frozen=True)
class MonitorTargetReport:
    generated_at: str
    source_review_decisions_path: str
    source_entry_plans_path: str
    source_user_symbols_path: str
    source_trade_report_path: str
    targets: list[MonitorTarget]
    warnings: list[str] = field(default_factory=list)


def build_monitor_target_report(
    *,
    review_decisions_path: Path | None = None,
    entry_plans_path: Path | None = None,
    user_symbols_path: Path | None = None,
    trade_report_path: Path | None = None,
    include_interested: bool = True,
    include_watchlist: bool = True,
    include_execution_ready: bool = True,
    include_user_defined: bool = True,
    generated_at: datetime | None = None,
) -> MonitorTargetReport:
    generated_at = generated_at or now_central()
    review_decisions_path = review_decisions_path or DATA_DIR / "review-decisions.json"
    entry_plans_path = entry_plans_path or DATA_DIR / "entry-plans.json"
    user_symbols_path = user_symbols_path or MONITOR_SYMBOLS_PATH
    trade_report_path = trade_report_path or latest_trade_report_path()
    targets: dict[str, MonitorTarget] = {}
    warnings: list[str] = []

    decisions = load_review_decisions(review_decisions_path)
    entry_plans = load_entry_plans(entry_plans_path)
    user_symbols = load_user_defined_symbols(user_symbols_path)

    add_review_decision_targets(
        targets,
        decisions,
        include_interested=include_interested,
        include_watchlist=include_watchlist,
    )
    add_entry_plan_targets(targets, entry_plans)

    if include_user_defined:
        add_user_defined_targets(targets, user_symbols)

    if include_execution_ready:
        if trade_report_path and trade_report_path.exists():
            add_execution_ready_targets(targets, trade_report_path)
        else:
            warnings.append("NO_TRADE_PLANNING_REPORT")

    for target in targets.values():
        target.sources = sorted(set(target.sources), key=lambda source: (-TARGET_SOURCES.get(source, 0), source))
        target.review_statuses = sorted(set(target.review_statuses))
        target.notes = dedupe(target.notes)
        target.priority = max((TARGET_SOURCES.get(source, 0) for source in target.sources), default=0)

    rows = sorted(targets.values(), key=lambda target: (-target.priority, target.symbol))
    if not rows:
        warnings.append("NO_MONITOR_TARGETS")

    return MonitorTargetReport(
        generated_at=generated_at.isoformat(),
        source_review_decisions_path=str(review_decisions_path),
        source_entry_plans_path=str(entry_plans_path),
        source_user_symbols_path=str(user_symbols_path),
        source_trade_report_path=str(trade_report_path or ""),
        targets=rows,
        warnings=dedupe(warnings),
    )


def add_review_decision_targets(
    targets: dict[str, MonitorTarget],
    decisions: dict[str, ReviewDecision],
    *,
    include_interested: bool,
    include_watchlist: bool,
) -> None:
    for decision in decisions.values():
        status = decision.review_status
        if status == ReviewStatus.WATCHLIST and include_watchlist:
            target = ensure_target(targets, decision.identity.ticker)
            target.sources.append("watchlist")
            target.review_statuses.append(status.value)
            if decision.decision_note:
                target.notes.append(decision.decision_note)
        elif status == ReviewStatus.INTERESTED and include_interested:
            target = ensure_target(targets, decision.identity.ticker)
            target.sources.append("interested")
            target.review_statuses.append(status.value)
            if decision.decision_note:
                target.notes.append(decision.decision_note)


def add_entry_plan_targets(targets: dict[str, MonitorTarget], entry_plans: dict[str, EntryPlan]) -> None:
    for plan in entry_plans.values():
        target = ensure_target(targets, plan.identity.ticker)
        target.sources.append("entry_plan")
        target.entry_plan_status = "complete" if plan.plan_complete else "incomplete"
        for note in [plan.thesis, plan.invalidation, plan.notes]:
            if note:
                target.notes.append(note)


def add_user_defined_targets(targets: dict[str, MonitorTarget], symbols: dict[str, UserDefinedMonitorSymbol]) -> None:
    for item in symbols.values():
        if not item.enabled:
            continue
        target = ensure_target(targets, item.symbol)
        target.sources.append("user_defined")
        if item.notes:
            target.notes.append(item.notes)


def add_execution_ready_targets(targets: dict[str, MonitorTarget], trade_report_path: Path) -> None:
    payload = json.loads(trade_report_path.read_text(encoding="utf-8"))
    for item in payload.get("candidates", []):
        symbol = normalize_symbol(item.get("symbol") or item.get("ticker"))
        if not symbol:
            continue
        readiness = str((item.get("trade_plan") or {}).get("readiness") or item.get("readiness") or "")
        if readiness not in {EXECUTION_READY_PREMARKET, EXECUTION_READY_TRADE}:
            continue
        target = ensure_target(targets, symbol)
        target.sources.append("execution_ready")
        target.execution_state = readiness
        target.latest_trade_report = str(trade_report_path)


def ensure_target(targets: dict[str, MonitorTarget], symbol: str) -> MonitorTarget:
    symbol = normalize_symbol(symbol)
    if symbol not in targets:
        targets[symbol] = MonitorTarget(symbol=symbol)
    return targets[symbol]


def load_user_defined_symbols(path: Path | None = None) -> dict[str, UserDefinedMonitorSymbol]:
    path = path or MONITOR_SYMBOLS_PATH
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_symbols = payload.get("symbols", payload if isinstance(payload, list) else [])
    symbols: dict[str, UserDefinedMonitorSymbol] = {}
    for item in raw_symbols:
        if isinstance(item, str):
            record = UserDefinedMonitorSymbol(symbol=normalize_symbol(item))
        elif isinstance(item, dict):
            record = user_defined_symbol_from_dict(item)
        else:
            continue
        if record.symbol:
            symbols[record.symbol] = record
    return symbols


def save_user_defined_symbols(symbols: dict[str, UserDefinedMonitorSymbol], path: Path | None = None) -> Path:
    path = path or MONITOR_SYMBOLS_PATH
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "updated_at": now_central().isoformat(),
        "symbols": [asdict(item) for item in sorted(symbols.values(), key=lambda item: item.symbol)],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def upsert_user_defined_symbol(
    symbol: str,
    *,
    notes: str = "",
    enabled: bool = True,
    path: Path | None = None,
) -> UserDefinedMonitorSymbol:
    path = path or MONITOR_SYMBOLS_PATH
    symbols = load_user_defined_symbols(path)
    normalized = normalize_symbol(symbol)
    record = UserDefinedMonitorSymbol(
        symbol=normalized,
        notes=notes.strip(),
        enabled=enabled,
        added_at=symbols.get(normalized, UserDefinedMonitorSymbol(normalized)).added_at or now_central().isoformat(),
    )
    symbols[normalized] = record
    save_user_defined_symbols(symbols, path)
    return record


def remove_user_defined_symbol(symbol: str, path: Path | None = None) -> bool:
    path = path or MONITOR_SYMBOLS_PATH
    symbols = load_user_defined_symbols(path)
    normalized = normalize_symbol(symbol)
    if normalized not in symbols:
        return False
    del symbols[normalized]
    save_user_defined_symbols(symbols, path)
    return True


def export_monitor_target_report(report: MonitorTargetReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = safe_timestamp(report.generated_at)
    base = f"opportunity-monitor-targets-{timestamp}"
    csv_path = output_dir / f"{base}.csv"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_monitor_target_csv(report, csv_path)
    write_monitor_target_json(report, json_path)
    write_monitor_target_markdown(report, md_path)
    return {"csv": csv_path, "json": json_path, "report": md_path}


def write_monitor_target_csv(report: MonitorTargetReport, path: Path) -> None:
    columns = [
        "Symbol",
        "Priority",
        "Sources",
        "Review Statuses",
        "Entry Plan Status",
        "Execution State",
        "Latest Trade Report",
        "Notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for target in report.targets:
            writer.writerow(
                {
                    "Symbol": target.symbol,
                    "Priority": target.priority,
                    "Sources": ", ".join(target.sources),
                    "Review Statuses": ", ".join(target.review_statuses),
                    "Entry Plan Status": target.entry_plan_status,
                    "Execution State": target.execution_state,
                    "Latest Trade Report": target.latest_trade_report,
                    "Notes": " | ".join(target.notes),
                }
            )


def write_monitor_target_json(report: MonitorTargetReport, path: Path) -> None:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "metadata": {
            "generated_at": report.generated_at,
            "source_review_decisions_path": report.source_review_decisions_path,
            "source_entry_plans_path": report.source_entry_plans_path,
            "source_user_symbols_path": report.source_user_symbols_path,
            "source_trade_report_path": report.source_trade_report_path,
            "warnings": report.warnings,
        },
        "targets": [asdict(target) for target in report.targets],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_monitor_target_markdown(report: MonitorTargetReport, path: Path) -> None:
    lines = [
        "# Momentum Hunter Opportunity Monitor Targets",
        "",
        "Derived monitor target report only. This does not fetch market data, place orders, or mutate raw captures.",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Review decisions: `{report.source_review_decisions_path}`",
        f"- Entry plans: `{report.source_entry_plans_path}`",
        f"- User symbols: `{report.source_user_symbols_path}`",
        f"- Trade report: `{report.source_trade_report_path or 'none'}`",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] or ["- None"])
    lines.extend(
        [
            "",
            "## Targets",
            "",
            "| Symbol | Priority | Sources | Review | Plan | Execution State | Notes |",
            "| --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    if not report.targets:
        lines.append("| NONE | 0 | - | - | - | - | No monitor targets resolved |")
    for target in report.targets:
        lines.append(
            "| "
            + " | ".join(
                [
                    target.symbol,
                    str(target.priority),
                    ", ".join(target.sources) or "-",
                    ", ".join(target.review_statuses) or "-",
                    target.entry_plan_status or "-",
                    target.execution_state or "-",
                    "; ".join(target.notes) or "-",
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def latest_trade_report_path(reports_dir: Path | None = None) -> Path | None:
    reports_dir = reports_dir or DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("event-trade-plan-briefing-*.json")) + list(reports_dir.glob("trade-plan-briefing-*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def user_defined_symbol_from_dict(payload: dict) -> UserDefinedMonitorSymbol:
    return UserDefinedMonitorSymbol(
        symbol=normalize_symbol(payload.get("symbol", "")),
        notes=str(payload.get("notes", "")),
        enabled=bool(payload.get("enabled", True)),
        added_at=str(payload.get("added_at", "")),
    )


def normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def safe_timestamp(value: str) -> str:
    return "".join(char for char in value if char.isdigit() or char == "T")[:32] or now_central().strftime("%Y%m%dT%H%M%S")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Momentum Hunter opportunity monitor targets.")
    parser.add_argument("--trade-report", type=Path, default=None)
    parser.add_argument("--review-decisions", type=Path, default=None)
    parser.add_argument("--entry-plans", type=Path, default=None)
    parser.add_argument("--user-symbols", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--exclude-interested", action="store_true")
    parser.add_argument("--exclude-watchlist", action="store_true")
    parser.add_argument("--exclude-execution-ready", action="store_true")
    parser.add_argument("--exclude-user-defined", action="store_true")
    args = parser.parse_args(argv)

    report = build_monitor_target_report(
        review_decisions_path=args.review_decisions,
        entry_plans_path=args.entry_plans,
        user_symbols_path=args.user_symbols,
        trade_report_path=args.trade_report,
        include_interested=not args.exclude_interested,
        include_watchlist=not args.exclude_watchlist,
        include_execution_ready=not args.exclude_execution_ready,
        include_user_defined=not args.exclude_user_defined,
    )
    paths = export_monitor_target_report(report, args.output_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
