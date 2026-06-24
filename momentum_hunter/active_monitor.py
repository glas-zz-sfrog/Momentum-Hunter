from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.monitor_targets import (
    MonitorTargetReport,
    build_monitor_target_report,
    export_monitor_target_report,
    latest_trade_report_path,
)
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OPPORTUNITY_MONITOR_STATE_PATH,
    OPPORTUNITY_OBSERVATIONS_PATH,
    OpportunityAlertReport,
    build_opportunity_alert_report,
    export_opportunity_alert_report,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    MarketTape,
    TechnicalLevels,
    apply_rvol_policy,
    build_http_session,
    build_trade_planning_report,
    classify_readiness,
    export_trade_planning_report,
    fetch_market_tape,
    latest_capture_path,
    parse_datetime,
    rvol_type_for_time,
)


MONITOR_CYCLE_SCHEMA_VERSION = 1
ACTIVE_MONITOR_STATUS_PATH = DATA_DIR / "active-monitor-status.json"


@dataclass(frozen=True)
class ActiveMonitorStatus:
    state: str
    started_at: str
    updated_at: str
    cycles_requested: int
    cycles_completed: int
    interval_seconds: int
    fetch_missing_market_data: bool
    refresh_target_market_data: bool = False
    last_cycle_at: str = ""
    next_cycle_at: str = ""
    last_report_path: str = ""
    last_error: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MonitorCycleReport:
    generated_at: str
    trade_report_path: str
    target_symbols: list[str]
    target_count: int
    trade_report_symbol_count: int
    matched_target_count: int
    missing_target_symbols: list[str]
    new_alert_count: int
    active_alert_count: int
    tracked_alert_count: int
    state_transition_count: int
    coverage_row_count: int
    covered_missing_symbols: list[str]
    uncovered_missing_symbols: list[str]
    coverage_report_path: str
    target_report_paths: dict[str, str]
    alert_report_paths: dict[str, str]
    refreshed_target_count: int = 0
    market_data_refresh_report_path: str = ""
    readiness_recalculated_count: int = 0
    readiness_changed_count: int = 0
    warnings: list[str] = field(default_factory=list)


def run_monitor_cycle(
    *,
    trade_report_path: Path | None = None,
    capture_path: Path | None = None,
    output_dir: Path | None = None,
    review_decisions_path: Path | None = None,
    entry_plans_path: Path | None = None,
    user_symbols_path: Path | None = None,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    state_path: Path = OPPORTUNITY_MONITOR_STATE_PATH,
    observations_path: Path = OPPORTUNITY_OBSERVATIONS_PATH,
    fetch_bars: bool = False,
    fetch_market_data: bool = False,
    fetch_missing_market_data: bool = False,
    refresh_target_market_data: bool = False,
    market_tape_by_symbol: dict[str, MarketTape] | None = None,
    event_mode: bool = False,
    generated_at: datetime | None = None,
    status_path: Path | None = None,
) -> MonitorCycleReport:
    generated_at = generated_at or now_central()
    started_at = now_central()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    active_trade_report = prepare_trade_report(
        trade_report_path=trade_report_path,
        capture_path=capture_path,
        output_dir=output_dir,
        fetch_bars=fetch_bars,
        fetch_market_data=fetch_market_data,
        event_mode=event_mode,
        as_of=generated_at,
    )
    if not active_trade_report:
        warnings.append("NO_TRADE_PLANNING_REPORT")
        target_report = build_monitor_target_report(
            review_decisions_path=review_decisions_path,
            entry_plans_path=entry_plans_path,
            user_symbols_path=user_symbols_path,
            trade_report_path=None,
            generated_at=generated_at,
        )
        target_paths = export_monitor_target_report(target_report, output_dir)
        report = MonitorCycleReport(
            generated_at=generated_at.isoformat(),
            trade_report_path="",
            target_symbols=[target.symbol for target in target_report.targets],
            target_count=len(target_report.targets),
            trade_report_symbol_count=0,
            matched_target_count=0,
            missing_target_symbols=[target.symbol for target in target_report.targets],
            new_alert_count=0,
            active_alert_count=0,
            tracked_alert_count=0,
            state_transition_count=0,
            coverage_row_count=0,
            covered_missing_symbols=[],
            uncovered_missing_symbols=[target.symbol for target in target_report.targets],
            coverage_report_path="",
            target_report_paths=stringify_paths(target_paths),
            alert_report_paths={},
            refreshed_target_count=0,
            market_data_refresh_report_path="",
            readiness_recalculated_count=0,
            readiness_changed_count=0,
            warnings=dedupe(warnings + target_report.warnings),
        )
        paths = export_monitor_cycle_report(report, output_dir)
        write_one_shot_monitor_status(
            report,
            paths=paths,
            status_path=status_path,
            started_at=started_at,
            fetch_missing_market_data=fetch_missing_market_data,
            refresh_target_market_data=refresh_target_market_data,
        )
        return report

    target_report = build_monitor_target_report(
        review_decisions_path=review_decisions_path,
        entry_plans_path=entry_plans_path,
        user_symbols_path=user_symbols_path,
        trade_report_path=active_trade_report,
        generated_at=generated_at,
    )
    target_paths = export_monitor_target_report(target_report, output_dir)
    target_symbols = {target.symbol for target in target_report.targets}
    trade_symbols = trade_report_symbols(active_trade_report)
    missing_symbols = sorted(target_symbols - trade_symbols)
    if missing_symbols:
        warnings.append("TARGETS_WITHOUT_SOURCE_TRADE_ROWS")

    target_market_tapes = build_target_market_tapes(
        target_symbols,
        generated_at=generated_at,
        market_tape_by_symbol=market_tape_by_symbol,
        fetch_market_data=refresh_target_market_data,
    )
    alert_trade_report = active_trade_report
    market_data_refresh_report_path = ""
    refreshed_target_count = 0
    readiness_recalculated_count = 0
    readiness_changed_count = 0
    if refresh_target_market_data:
        (
            alert_trade_report,
            refreshed_target_count,
            readiness_recalculated_count,
            readiness_changed_count,
            market_data_refresh_report_path,
        ) = write_refreshed_target_trade_report(
            active_trade_report,
            target_symbols=target_symbols,
            market_tape_by_symbol=target_market_tapes,
            output_dir=output_dir,
            generated_at=generated_at,
        )
        if refreshed_target_count:
            warnings.append("TARGET_MARKET_DATA_REFRESHED")
        else:
            warnings.append("TARGET_MARKET_DATA_REFRESH_NO_TAPE")
        if readiness_changed_count:
            warnings.append("TARGET_READINESS_RECALCULATED_FROM_REFRESHED_TAPE")

    coverage_rows = build_missing_target_coverage_rows(
        missing_symbols,
        target_report=target_report,
        generated_at=generated_at,
        market_tape_by_symbol=target_market_tapes,
        fetch_missing_market_data=fetch_missing_market_data and not refresh_target_market_data,
    )
    coverage_symbols = sorted(str(row.get("symbol", "")).upper() for row in coverage_rows if row.get("symbol"))
    uncovered_missing_symbols = sorted(set(missing_symbols) - set(coverage_symbols))
    coverage_report_path = ""
    if coverage_rows:
        alert_trade_report = write_coverage_trade_report(
            alert_trade_report,
            coverage_rows,
            output_dir=output_dir,
            generated_at=generated_at,
        )
        coverage_report_path = str(alert_trade_report)
        warnings.append("COVERAGE_ROWS_ADDED_FOR_MISSING_TARGETS")
        if any(row_without_market_data(row) for row in coverage_rows):
            warnings.append("COVERAGE_ROWS_WITHOUT_MARKET_DATA")

    alert_report = build_opportunity_alert_report(
        alert_trade_report,
        alerts_path=alerts_path,
        state_path=state_path,
        observations_path=observations_path,
        generated_at=generated_at,
        target_symbols=target_symbols,
    )
    alert_paths = export_opportunity_alert_report(alert_report, output_dir)
    report = MonitorCycleReport(
        generated_at=generated_at.isoformat(),
        trade_report_path=str(alert_trade_report),
        target_symbols=sorted(target_symbols),
        target_count=len(target_symbols),
        trade_report_symbol_count=len(trade_symbols),
        matched_target_count=len(sorted((target_symbols & trade_symbols) | set(coverage_symbols))),
        missing_target_symbols=missing_symbols,
        new_alert_count=len(alert_report.new_alerts),
        active_alert_count=len(alert_report.active_alerts),
        tracked_alert_count=len(alert_report.tracked_alerts),
        state_transition_count=len(alert_report.state_transitions),
        coverage_row_count=len(coverage_rows),
        covered_missing_symbols=coverage_symbols,
        uncovered_missing_symbols=uncovered_missing_symbols,
        coverage_report_path=coverage_report_path,
        target_report_paths=stringify_paths(target_paths),
        alert_report_paths=stringify_paths(alert_paths),
        refreshed_target_count=refreshed_target_count,
        market_data_refresh_report_path=market_data_refresh_report_path,
        readiness_recalculated_count=readiness_recalculated_count,
        readiness_changed_count=readiness_changed_count,
        warnings=dedupe(warnings + target_report.warnings + alert_report.warnings),
    )
    paths = export_monitor_cycle_report(report, output_dir)
    write_one_shot_monitor_status(
        report,
        paths=paths,
        status_path=status_path,
        started_at=started_at,
        fetch_missing_market_data=fetch_missing_market_data,
        refresh_target_market_data=refresh_target_market_data,
    )
    return report


def run_monitor_loop(
    *,
    cycles: int = 1,
    interval_seconds: int = 900,
    status_path: Path = ACTIVE_MONITOR_STATUS_PATH,
    sleep_fn=time.sleep,
    cycle_runner=run_monitor_cycle,
    continue_on_error: bool = False,
    **cycle_kwargs,
) -> MonitorCycleReport | None:
    cycles = max(1, cycles)
    interval_seconds = max(1, interval_seconds)
    started_at = now_central()
    status = ActiveMonitorStatus(
        state="RUNNING",
        started_at=started_at.isoformat(),
        updated_at=started_at.isoformat(),
        cycles_requested=cycles,
        cycles_completed=0,
        interval_seconds=interval_seconds,
        fetch_missing_market_data=bool(cycle_kwargs.get("fetch_missing_market_data", False)),
        refresh_target_market_data=bool(cycle_kwargs.get("refresh_target_market_data", False)),
    )
    save_active_monitor_status(status, status_path)
    final_report: MonitorCycleReport | None = None

    for index in range(cycles):
        cycle_started = now_central()
        status = replace(
            status,
            state="RUNNING",
            updated_at=cycle_started.isoformat(),
            next_cycle_at="",
            last_error="",
        )
        save_active_monitor_status(status, status_path)
        try:
            final_report = cycle_runner(**cycle_kwargs)
        except Exception as exc:
            failed_at = now_central()
            status = replace(
                status,
                state="FAILED",
                updated_at=failed_at.isoformat(),
                cycles_completed=index,
                last_error=f"{type(exc).__name__}: {exc}",
                next_cycle_at="",
            )
            save_active_monitor_status(status, status_path)
            if not continue_on_error:
                raise
            if index < cycles - 1:
                sleep_fn(interval_seconds)
            continue

        completed = index + 1
        updated_at = now_central()
        next_cycle_at = (
            (updated_at + timedelta(seconds=interval_seconds)).isoformat()
            if index < cycles - 1
            else ""
        )
        status = replace(
            status,
            state="RUNNING" if index < cycles - 1 else "IDLE",
            updated_at=updated_at.isoformat(),
            cycles_completed=completed,
            last_cycle_at=final_report.generated_at,
            next_cycle_at=next_cycle_at,
            last_report_path=str(latest_monitor_cycle_json_path(cycle_kwargs.get("output_dir")) or ""),
            last_error="",
            warnings=list(final_report.warnings),
        )
        save_active_monitor_status(status, status_path)
        if index < cycles - 1:
            sleep_fn(interval_seconds)

    return final_report


def load_active_monitor_status(path: Path = ACTIVE_MONITOR_STATUS_PATH) -> ActiveMonitorStatus | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return active_monitor_status_from_dict(payload)


def save_active_monitor_status(status: ActiveMonitorStatus, path: Path = ACTIVE_MONITOR_STATUS_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(status), indent=2), encoding="utf-8")
    return path


def write_one_shot_monitor_status(
    report: MonitorCycleReport,
    *,
    paths: dict[str, Path],
    status_path: Path | None,
    started_at: datetime,
    fetch_missing_market_data: bool,
    refresh_target_market_data: bool,
) -> None:
    if status_path is None:
        return
    updated_at = now_central()
    status = ActiveMonitorStatus(
        state="IDLE",
        started_at=started_at.isoformat(),
        updated_at=updated_at.isoformat(),
        cycles_requested=1,
        cycles_completed=1,
        interval_seconds=0,
        fetch_missing_market_data=fetch_missing_market_data,
        refresh_target_market_data=refresh_target_market_data,
        last_cycle_at=report.generated_at,
        last_report_path=str(paths.get("json", "")),
        warnings=list(report.warnings),
    )
    save_active_monitor_status(status, status_path)


def active_monitor_status_from_dict(payload: dict) -> ActiveMonitorStatus:
    return ActiveMonitorStatus(
        state=str(payload.get("state", "")),
        started_at=str(payload.get("started_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        cycles_requested=parse_int(payload.get("cycles_requested"), default=0),
        cycles_completed=parse_int(payload.get("cycles_completed"), default=0),
        interval_seconds=parse_int(payload.get("interval_seconds"), default=0),
        fetch_missing_market_data=bool(payload.get("fetch_missing_market_data", False)),
        refresh_target_market_data=bool(payload.get("refresh_target_market_data", False)),
        last_cycle_at=str(payload.get("last_cycle_at", "")),
        next_cycle_at=str(payload.get("next_cycle_at", "")),
        last_report_path=str(payload.get("last_report_path", "")),
        last_error=str(payload.get("last_error", "")),
        warnings=list(payload.get("warnings", [])) if isinstance(payload.get("warnings"), list) else [],
    )


def latest_monitor_cycle_json_path(output_dir: Path | None = None) -> Path | None:
    reports_dir = output_dir or DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("active-monitor-cycle-*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def build_target_market_tapes(
    symbols: set[str],
    *,
    generated_at: datetime,
    market_tape_by_symbol: dict[str, MarketTape] | None = None,
    fetch_market_data: bool = False,
) -> dict[str, MarketTape]:
    tapes = {key.upper(): value for key, value in (market_tape_by_symbol or {}).items()}
    session = build_http_session() if fetch_market_data else None
    rvol_type = rvol_type_for_time(generated_at)
    for symbol in sorted(symbols):
        tape = tapes.get(symbol)
        if tape is None and session is not None:
            tape = fetch_market_tape(session, symbol)
        if tape is not None:
            tapes[symbol] = apply_rvol_policy(tape, rvol_type)
    return tapes


def write_refreshed_target_trade_report(
    source_trade_report_path: Path,
    *,
    target_symbols: set[str],
    market_tape_by_symbol: dict[str, MarketTape],
    output_dir: Path,
    generated_at: datetime,
) -> tuple[Path, int, int, int, str]:
    if not target_symbols or not market_tape_by_symbol:
        return source_trade_report_path, 0, 0, 0, ""
    payload = json.loads(source_trade_report_path.read_text(encoding="utf-8"))
    refreshed_count = 0
    readiness_recalculated_count = 0
    readiness_changed_count = 0
    refreshed_symbols: list[str] = []
    candidates = payload.get("candidates", [])
    for item in candidates:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
        if symbol not in target_symbols:
            continue
        tape = market_tape_by_symbol.get(symbol)
        if tape is None:
            continue
        refresh_result = update_trade_candidate_market_tape(item, tape, generated_at=generated_at)
        refreshed_count += 1
        if refresh_result.get("readiness_recalculated"):
            readiness_recalculated_count += 1
        if refresh_result.get("readiness_changed"):
            readiness_changed_count += 1
        refreshed_symbols.append(symbol)
    if not refreshed_count:
        return source_trade_report_path, 0, 0, 0, ""

    metadata = dict(payload.get("metadata", {}))
    metadata["generated_at"] = generated_at.isoformat()
    metadata["monitor_market_data_refresh_source_report"] = str(source_trade_report_path)
    metadata["monitor_market_data_refreshed_symbol_count"] = refreshed_count
    metadata["monitor_market_data_refreshed_symbols"] = sorted(refreshed_symbols)
    metadata["monitor_readiness_recalculated_count"] = readiness_recalculated_count
    metadata["monitor_readiness_changed_count"] = readiness_changed_count
    metadata["monitor_market_data_refresh_warning"] = (
        "Market tape was refreshed by Active Monitor; readiness was recalculated in this derived report only."
    )
    payload["metadata"] = metadata
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"active-monitor-refresh-{safe_timestamp(generated_at.isoformat())}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path, refreshed_count, readiness_recalculated_count, readiness_changed_count, str(path)


def update_trade_candidate_market_tape(item: dict, tape: MarketTape, *, generated_at: datetime) -> dict[str, object]:
    tape_payload = market_tape_payload(tape)
    market_data = dict(item.get("market_data") or {})
    market_data.update(tape_payload)
    market_data["twenty_day_average_daily_volume"] = tape_payload.get("average_daily_volume_20")
    item["market_data"] = market_data
    item["market_tape"] = tape_payload
    old_readiness, new_readiness, confidence, tradeability, blocking_reasons = recalculate_readiness_from_report_row(item, tape)
    readiness_recalculated = bool(new_readiness)
    readiness_changed = bool(old_readiness and new_readiness and old_readiness != new_readiness)
    if readiness_recalculated:
        trade_plan = dict(item.get("trade_plan") or {})
        warnings = list(trade_plan.get("warnings", [])) if isinstance(trade_plan.get("warnings"), list) else []
        trade_plan["readiness"] = new_readiness
        trade_plan["confidence"] = confidence
        trade_plan["tradeability"] = tradeability
        trade_plan["blocking_reasons"] = blocking_reasons
        trade_plan["warnings"] = dedupe(warnings + ["READINESS_RECALCULATED_FROM_REFRESHED_TAPE"])
        item["trade_plan"] = trade_plan
    item["monitor_market_data_refresh"] = {
        "refreshed_at": generated_at.isoformat(),
        "source": tape.source,
        "previous_readiness": old_readiness,
        "recalculated_readiness": new_readiness,
        "readiness_changed": readiness_changed,
        "warning": "Market tape refreshed for monitoring; readiness was recalculated in this derived report only.",
    }
    return {
        "readiness_recalculated": readiness_recalculated,
        "readiness_changed": readiness_changed,
        "old_readiness": old_readiness,
        "new_readiness": new_readiness,
    }


def recalculate_readiness_from_report_row(item: dict, tape: MarketTape) -> tuple[str, str, str, str, list[str]]:
    trade_plan = item.get("trade_plan") if isinstance(item.get("trade_plan"), dict) else {}
    old_readiness = str(trade_plan.get("readiness", "") if trade_plan else "")
    technicals = technical_levels_from_report_row(item)
    current_price = tape.last_price if tape.last_price is not None else tape.premarket_price
    if current_price is None:
        market = item.get("market_data") if isinstance(item.get("market_data"), dict) else {}
        current_price = parse_float(market.get("last_price") or market.get("premarket_price"))
    original_entry = parse_float(trade_plan.get("bullish_entry") if trade_plan else None)
    if original_entry is None:
        original_entry = technicals.resistance_level
    readiness, confidence, tradeability, blocking_reasons = classify_readiness(
        technicals,
        tape,
        current_price=current_price,
        original_entry=original_entry,
    )
    return old_readiness, readiness, confidence, tradeability, blocking_reasons


def technical_levels_from_report_row(item: dict) -> TechnicalLevels:
    tech = item.get("technical_levels") if isinstance(item.get("technical_levels"), dict) else {}
    return TechnicalLevels(
        previous_day_high=parse_float(tech.get("previous_day_high")),
        previous_day_low=parse_float(tech.get("previous_day_low")),
        previous_day_close=parse_float(tech.get("previous_day_close")),
        five_day_high=parse_float(tech.get("five_day_high")),
        twenty_day_high=parse_float(tech.get("twenty_day_high")),
        atr=parse_float(tech.get("atr")),
        support_level=parse_float(tech.get("support_level")),
        resistance_level=parse_float(tech.get("resistance_level")),
        source=str(tech.get("source") or "daily_bars"),
        warnings=list(tech.get("warnings", [])) if isinstance(tech.get("warnings"), list) else [],
    )


def build_missing_target_coverage_rows(
    missing_symbols: list[str],
    *,
    target_report: MonitorTargetReport,
    generated_at: datetime,
    market_tape_by_symbol: dict[str, MarketTape] | None = None,
    fetch_missing_market_data: bool = False,
) -> list[dict]:
    if not missing_symbols:
        return []
    market_tape_by_symbol = {key.upper(): value for key, value in (market_tape_by_symbol or {}).items()}
    target_by_symbol = {target.symbol: target for target in target_report.targets}
    session = build_http_session() if fetch_missing_market_data else None
    rows: list[dict] = []
    for symbol in missing_symbols:
        tape = market_tape_by_symbol.get(symbol)
        if tape is None and session is not None:
            tape = fetch_market_tape(session, symbol)
        if tape is not None:
            tape = apply_rvol_policy(tape, rvol_type_for_time(generated_at))
        rows.append(coverage_row_for_target(symbol, target_by_symbol.get(symbol), tape))
    return rows


def coverage_row_for_target(symbol: str, target, tape: MarketTape | None) -> dict:
    warnings = ["COVERAGE_ROW_NOT_FROM_SCANNER", "MISSING_SCANNER_CONTEXT"]
    if tape is None:
        warnings.append("MISSING_MARKET_TAPE")
    elif tape.warnings:
        warnings.extend(tape.warnings)
    notes = list(getattr(target, "notes", []) or [])
    sources = list(getattr(target, "sources", []) or [])
    return {
        "symbol": symbol,
        "company": "",
        "sector": "",
        "industry": "",
        "market_data": market_tape_payload(tape),
        "technical_levels": {
            "previous_day_high": None,
            "previous_day_low": None,
            "previous_day_close": None,
            "five_day_high": None,
            "twenty_day_high": None,
            "support_level": None,
            "resistance_level": None,
            "atr": None,
            "source": "monitor_coverage",
            "warnings": ["MISSING_TECHNICAL_LEVELS"],
        },
        "trade_plan": {
            "readiness": "MONITORING_ONLY",
            "bullish_entry": None,
            "bullish_stop": None,
            "bullish_target_1": None,
            "bullish_target_2": None,
            "risk_reward_ratio": None,
            "warnings": warnings,
            "blocking_reasons": ["MONITOR_COVERAGE_ONLY"],
        },
        "scoring": {
            "momentum_score": 0,
            "news_score": 0,
            "composite_score": 0,
            "catalyst_summary": "Monitor coverage row; target was absent from source trade-planning report.",
            "catalyst_cluster": "Monitor Coverage",
            "catalyst_confidence": 0,
        },
        "monitor_coverage": {
            "sources": sources,
            "notes": notes,
            "warning": "This row was generated by the monitor cycle because the symbol was missing from the source scanner/trade report.",
        },
    }


def market_tape_payload(tape: MarketTape | None) -> dict:
    if tape is None:
        return {
            "last_price": None,
            "premarket_price": None,
            "premarket_percent": None,
            "premarket_volume": None,
            "intraday_volume": None,
            "average_daily_volume_20": None,
            "rvol_formula_used": "",
            "rvol_numerator": None,
            "rvol_denominator": None,
            "rvol_type": "",
            "current_bid": None,
            "current_ask": None,
            "spread_percent": None,
            "relative_volume": None,
            "source": "monitor_coverage_missing_tape",
            "warnings": ["MISSING_MARKET_TAPE"],
        }
    return asdict(tape)


def row_without_market_data(row: dict) -> bool:
    market = row.get("market_data") or {}
    return market.get("last_price") is None and market.get("premarket_price") is None


def write_coverage_trade_report(
    source_trade_report_path: Path,
    coverage_rows: list[dict],
    *,
    output_dir: Path,
    generated_at: datetime,
) -> Path:
    payload = json.loads(source_trade_report_path.read_text(encoding="utf-8"))
    metadata = dict(payload.get("metadata", {}))
    metadata["generated_at"] = generated_at.isoformat()
    metadata["monitor_coverage_source_report"] = str(source_trade_report_path)
    metadata["monitor_coverage_row_count"] = len(coverage_rows)
    metadata["monitor_coverage_warning"] = "Contains monitor coverage rows for targets absent from source trade-planning report."
    payload["metadata"] = metadata
    payload["candidates"] = list(payload.get("candidates", [])) + coverage_rows
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"active-monitor-coverage-{safe_timestamp(generated_at.isoformat())}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def prepare_trade_report(
    *,
    trade_report_path: Path | None,
    capture_path: Path | None,
    output_dir: Path,
    fetch_bars: bool,
    fetch_market_data: bool,
    event_mode: bool,
    as_of: datetime,
) -> Path | None:
    if capture_path:
        report = build_trade_planning_report(
            capture_path,
            fetch_bars=fetch_bars or fetch_market_data,
            fetch_market_data=fetch_market_data,
            event_mode=event_mode,
            as_of=as_of,
        )
        return export_trade_planning_report(report, output_dir)["json"]
    if trade_report_path:
        return trade_report_path
    return latest_trade_report_path()


def export_monitor_cycle_report(report: MonitorCycleReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = safe_timestamp(report.generated_at)
    base = f"active-monitor-cycle-{stamp}"
    csv_path = output_dir / f"{base}.csv"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_monitor_cycle_csv(report, csv_path)
    write_monitor_cycle_json(report, json_path)
    write_monitor_cycle_markdown(report, md_path)
    return {"csv": csv_path, "json": json_path, "report": md_path}


def write_monitor_cycle_csv(report: MonitorCycleReport, path: Path) -> None:
    columns = [
        "Generated At",
        "Trade Report",
        "Target Count",
        "Matched Target Count",
        "Trade Report Symbol Count",
        "New Alerts",
        "Active Alerts",
        "Tracked Alerts",
        "State Transitions",
        "Coverage Rows",
        "Refreshed Targets",
        "Readiness Recalculated",
        "Readiness Changed",
        "Market Data Refresh Report",
        "Covered Missing Symbols",
        "Uncovered Missing Symbols",
        "Coverage Report",
        "Missing Target Symbols",
        "Warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "Generated At": report.generated_at,
                "Trade Report": report.trade_report_path,
                "Target Count": report.target_count,
                "Matched Target Count": report.matched_target_count,
                "Trade Report Symbol Count": report.trade_report_symbol_count,
                "New Alerts": report.new_alert_count,
                "Active Alerts": report.active_alert_count,
                "Tracked Alerts": report.tracked_alert_count,
                "State Transitions": report.state_transition_count,
                "Coverage Rows": report.coverage_row_count,
                "Refreshed Targets": report.refreshed_target_count,
                "Readiness Recalculated": report.readiness_recalculated_count,
                "Readiness Changed": report.readiness_changed_count,
                "Market Data Refresh Report": report.market_data_refresh_report_path,
                "Covered Missing Symbols": ", ".join(report.covered_missing_symbols),
                "Uncovered Missing Symbols": ", ".join(report.uncovered_missing_symbols),
                "Coverage Report": report.coverage_report_path,
                "Missing Target Symbols": ", ".join(report.missing_target_symbols),
                "Warnings": " | ".join(report.warnings),
            }
        )


def write_monitor_cycle_json(report: MonitorCycleReport, path: Path) -> None:
    payload = {
        "schema_version": MONITOR_CYCLE_SCHEMA_VERSION,
        "monitor_cycle": asdict(report),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_monitor_cycle_markdown(report: MonitorCycleReport, path: Path) -> None:
    lines = [
        "# Momentum Hunter Active Monitor Cycle",
        "",
        "Derived monitoring report only. This does not place orders, connect to a broker, or mutate raw captures.",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Trade report: `{report.trade_report_path or 'none'}`",
        f"- Targets: {report.target_count}",
        f"- Matched trade rows: {report.matched_target_count} of {report.trade_report_symbol_count}",
        f"- New alerts: {report.new_alert_count}",
        f"- Active alerts: {report.active_alert_count}",
        f"- Tracked alerts: {report.tracked_alert_count}",
        f"- State transitions: {report.state_transition_count}",
        f"- Coverage rows: {report.coverage_row_count}",
        f"- Refreshed target market-data rows: {report.refreshed_target_count}",
        f"- Recalculated readiness rows: {report.readiness_recalculated_count}",
        f"- Changed readiness rows: {report.readiness_changed_count}",
        f"- Market-data refresh report: `{report.market_data_refresh_report_path or 'none'}`",
        f"- Coverage report: `{report.coverage_report_path or 'none'}`",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings] or ["- None"])
    lines.extend(["", "## Target Symbols", ""])
    lines.append(", ".join(report.target_symbols) if report.target_symbols else "None")
    lines.extend(["", "## Missing Target Symbols", ""])
    lines.append(", ".join(report.missing_target_symbols) if report.missing_target_symbols else "None")
    lines.extend(["", "## Covered Missing Symbols", ""])
    lines.append(", ".join(report.covered_missing_symbols) if report.covered_missing_symbols else "None")
    lines.extend(["", "## Uncovered Missing Symbols", ""])
    lines.append(", ".join(report.uncovered_missing_symbols) if report.uncovered_missing_symbols else "None")
    lines.extend(["", "## Generated Artifacts", ""])
    for label, paths in [("Target report", report.target_report_paths), ("Alert report", report.alert_report_paths)]:
        lines.append(f"### {label}")
        if not paths:
            lines.append("- None")
            continue
        for kind, value in sorted(paths.items()):
            lines.append(f"- {kind}: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def trade_report_symbols(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = set()
    for item in payload.get("candidates", []):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
        if symbol:
            symbols.add(symbol)
    return symbols


def stringify_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in paths.items()}


def parse_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: object) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
    parser = argparse.ArgumentParser(description="Run a Momentum Hunter active monitor cycle.")
    parser.add_argument("--trade-report", type=Path, default=None, help="Existing trade-planning JSON report to monitor.")
    parser.add_argument("--capture", type=Path, default=None, help="Raw capture JSON to refresh into a trade report before monitoring.")
    parser.add_argument("--latest-capture", action="store_true", help="Use the latest raw capture to refresh a trade report.")
    parser.add_argument("--fetch-bars", action="store_true", help="Fetch daily bars when refreshing from a raw capture.")
    parser.add_argument("--fetch-market-data", action="store_true", help="Fetch live quote tape when refreshing from a raw capture.")
    parser.add_argument(
        "--fetch-missing-market-data",
        action="store_true",
        help="Fetch quote tape for monitor targets absent from the source trade-planning report.",
    )
    parser.add_argument(
        "--refresh-target-market-data",
        action="store_true",
        help="Fetch/refresh quote tape for all active monitor targets in a derived monitor report.",
    )
    parser.add_argument("--event-mode", action="store_true", help="Generate event-mode trade planning context when refreshing.")
    parser.add_argument("--as-of", default="", help="Override monitor cycle time, ISO format.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--state-path", type=Path, default=OPPORTUNITY_MONITOR_STATE_PATH)
    parser.add_argument("--observations-path", type=Path, default=OPPORTUNITY_OBSERVATIONS_PATH)
    parser.add_argument("--review-decisions", type=Path, default=None)
    parser.add_argument("--entry-plans", type=Path, default=None)
    parser.add_argument("--user-symbols", type=Path, default=None)
    parser.add_argument("--cycles", type=int, default=1, help="Number of monitor cycles to run. Defaults to one.")
    parser.add_argument("--interval-seconds", type=int, default=900, help="Delay between cycles when cycles > 1.")
    parser.add_argument("--status-path", type=Path, default=ACTIVE_MONITOR_STATUS_PATH)
    args = parser.parse_args(argv)

    as_of = parse_datetime(args.as_of) if args.as_of else None
    capture_path = args.capture
    if args.latest_capture and capture_path is None:
        capture_path = latest_capture_path()

    final_report = run_monitor_loop(
        cycles=args.cycles,
        interval_seconds=args.interval_seconds,
        status_path=args.status_path,
        trade_report_path=args.trade_report,
        capture_path=capture_path,
        output_dir=args.output_dir,
        review_decisions_path=args.review_decisions,
        entry_plans_path=args.entry_plans,
        user_symbols_path=args.user_symbols,
        alerts_path=args.alerts_path,
        state_path=args.state_path,
        observations_path=args.observations_path,
        fetch_bars=args.fetch_bars,
        fetch_market_data=args.fetch_market_data,
        fetch_missing_market_data=args.fetch_missing_market_data,
        refresh_target_market_data=args.refresh_target_market_data,
        event_mode=args.event_mode,
        generated_at=as_of,
    )
    assert final_report is not None
    paths = export_monitor_cycle_report(final_report, args.output_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
