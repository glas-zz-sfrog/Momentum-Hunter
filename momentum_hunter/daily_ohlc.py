from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.outcomes import build_http_session
from momentum_hunter.time_utils import now_central


DAILY_OHLC_ENGINE_VERSION = "daily_ohlc_research_source_v1"
DAILY_OHLC_SCHEMA_VERSION = 1

ANALYSIS_CAPTURES_PATH = DATA_DIR / "analysis-captures.csv"
OPPORTUNITY_ALERTS_PATH = DATA_DIR / "opportunity-alerts.json"
OPPORTUNITY_MINUTE_BARS_PATH = DATA_DIR / "opportunity-minute-bars.json"
DAILY_OHLC_SOURCE_PATH = DATA_DIR / "daily-ohlc-bars.json"
DAILY_OHLC_COVERAGE_LATEST_JSON = DATA_DIR / "reports" / "daily-ohlc-coverage-latest.json"
DAILY_OHLC_COVERAGE_LATEST_MD = DATA_DIR / "reports" / "daily-ohlc-coverage-latest.md"
DAILY_OHLC_COVERAGE_PLAN_LATEST_JSON = DATA_DIR / "reports" / "daily-ohlc-coverage-plan-latest.json"
DAILY_OHLC_COVERAGE_PLAN_LATEST_MD = DATA_DIR / "reports" / "daily-ohlc-coverage-plan-latest.md"

QUALITY_VALID = "VALID"
QUALITY_INVALID = "INVALID"
QUALITY_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"

REVIEW_DECISIONS_PATH = DATA_DIR / "review-decisions.json"
ENTRY_PLANS_PATH = DATA_DIR / "entry-plans.json"
SCORE_BREAKDOWNS_PATH = DATA_DIR / "score-breakdowns.json"
REPORTS_DIR = DATA_DIR / "reports"

BASELINE_SYMBOLS = ("QQQ", "SPY", "SMH", "SOXX")
CATEGORY_PRIORITY = {
    "broad_market_baseline": 0,
    "sector_etf_baseline": 0,
    "alert_symbols": 1,
    "outcome_symbols": 1,
    "current_watchlist": 1,
    "entry_plan_symbols": 1,
    "active_monitor_targets": 1,
    "recent_high_score_capture_symbols": 2,
    "candidate_story_symbols": 2,
    "repeated_capture_candidates": 2,
    "reviewed_candidates": 2,
    "research_candidates": 3,
    "recent_captures": 3,
}


@dataclass(frozen=True)
class DailyOhlcRecord:
    symbol: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    source: str
    adjusted: bool | None
    imported_at: str
    quality_status: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyOhlcLoadResult:
    source_path: str
    generated_at: str
    records: list[DailyOhlcRecord]
    valid_records: list[DailyOhlcRecord]
    invalid_records: list[DailyOhlcRecord]
    missing_symbols: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class DailyOhlcUniverseRow:
    symbol: str
    priority: int
    categories: list[str]
    source_counts: dict[str, int]
    latest_seen: str | None = None
    highest_score: float | None = None
    review_statuses: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DailyOhlcExpansionResult:
    generated_at: str
    requested_symbols: list[str]
    fetched_symbols: list[str]
    skipped_symbols: list[str]
    failed_symbols: list[str]
    existing_records: int
    fetched_records: int
    final_valid_records: int
    invalid_records: int
    cache_path: str
    warnings: list[str]


def build_daily_ohlc_universe(
    *,
    captures_path: Path = ANALYSIS_CAPTURES_PATH,
    outcomes_path: Path = DATA_DIR / "analysis-outcomes.csv",
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    reports_dir: Path = REPORTS_DIR,
    watchlist_dir: Path = DATA_DIR,
    high_score_threshold: float = 85.0,
    recent_capture_days: int = 14,
) -> list[DailyOhlcUniverseRow]:
    symbols: dict[str, dict[str, Any]] = {}

    def add_symbol(
        raw_symbol: str,
        category: str,
        *,
        seen_at: str | None = None,
        score: float | None = None,
        review_status: str | None = None,
        note: str | None = None,
    ) -> None:
        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            return
        item = symbols.setdefault(
            symbol,
            {
                "categories": set(),
                "source_counts": {},
                "latest_seen": None,
                "highest_score": None,
                "review_statuses": set(),
                "notes": set(),
            },
        )
        item["categories"].add(category)
        item["source_counts"][category] = item["source_counts"].get(category, 0) + 1
        if seen_at and (item["latest_seen"] is None or seen_at > item["latest_seen"]):
            item["latest_seen"] = seen_at
        if score is not None and (item["highest_score"] is None or score > item["highest_score"]):
            item["highest_score"] = score
        if review_status:
            item["review_statuses"].add(review_status)
        if note:
            item["notes"].add(note)

    for symbol in BASELINE_SYMBOLS:
        add_symbol(symbol, "broad_market_baseline" if symbol in {"QQQ", "SPY"} else "sector_etf_baseline")

    capture_rows = load_csv_rows(captures_path)
    latest_capture_date = max((row.get("capture_date", "") for row in capture_rows), default="")
    recent_cutoff = recent_cutoff_date(latest_capture_date, recent_capture_days)
    capture_counts: dict[str, int] = {}
    for row in capture_rows:
        symbol = normalize_symbol(row.get("ticker") or row.get("symbol"))
        if not symbol:
            continue
        capture_counts[symbol] = capture_counts.get(symbol, 0) + 1
        capture_date = str(row.get("capture_date") or "")
        score = parse_float(row.get("score"))
        add_symbol(symbol, "research_candidates", seen_at=capture_date, score=score)
        if capture_date and (recent_cutoff is None or capture_date >= recent_cutoff):
            add_symbol(symbol, "recent_captures", seen_at=capture_date, score=score)
        if score is not None and score >= high_score_threshold:
            add_symbol(symbol, "recent_high_score_capture_symbols", seen_at=capture_date, score=score)
    for symbol, count in capture_counts.items():
        if count >= 2:
            add_symbol(symbol, "repeated_capture_candidates", note=f"capture_count:{count}")
            add_symbol(symbol, "candidate_story_symbols", note="multiple captures support Candidate Story context")

    for row in load_csv_rows(outcomes_path):
        add_symbol(row.get("ticker") or row.get("symbol") or "", "outcome_symbols", seen_at=row.get("capture_date"))

    alerts = load_json_list(alerts_path, "alerts")
    for alert in alerts:
        add_symbol(str(alert.get("symbol") or ""), "alert_symbols", seen_at=str(alert.get("timestamp") or ""))

    decisions = load_json_mapping(review_decisions_path, "decisions")
    for decision in decisions.values():
        identity = decision.get("identity") if isinstance(decision, dict) else {}
        status = str(decision.get("review_status") or "") if isinstance(decision, dict) else ""
        category = "current_watchlist" if status.lower() == "watchlist" else "reviewed_candidates"
        add_symbol(
            str(identity.get("ticker") or ""),
            category,
            seen_at=str(decision.get("decision_timestamp") or ""),
            review_status=status,
        )

    plans = load_json_mapping(entry_plans_path, "plans")
    for plan in plans.values():
        identity = plan.get("identity") if isinstance(plan, dict) else {}
        add_symbol(str(identity.get("ticker") or ""), "entry_plan_symbols", seen_at=str(plan.get("updated_at") or ""))

    for item in load_latest_watchlist_items(watchlist_dir):
        add_symbol(str(item.get("ticker") or item.get("symbol") or ""), "current_watchlist", seen_at=str(item.get("saved_at") or ""))

    for target in load_latest_monitor_targets(reports_dir):
        add_symbol(str(target.get("symbol") or ""), "active_monitor_targets", note="latest active monitor target")

    score_records = load_json_mapping(score_breakdowns_path, "records")
    for record in score_records.values():
        identity = record.get("identity") if isinstance(record, dict) else {}
        add_symbol(
            str(record.get("ticker") or identity.get("ticker") or ""),
            "research_candidates",
            seen_at=str(record.get("capture_date") or identity.get("capture_date") or ""),
            score=parse_float(record.get("final_score") or record.get("computed_final_score")),
        )

    rows: list[DailyOhlcUniverseRow] = []
    for symbol, item in symbols.items():
        categories = sorted(item["categories"], key=lambda category: (CATEGORY_PRIORITY.get(category, 99), category))
        priority = min(CATEGORY_PRIORITY.get(category, 99) for category in categories) if categories else 99
        rows.append(
            DailyOhlcUniverseRow(
                symbol=symbol,
                priority=priority,
                categories=categories,
                source_counts=dict(sorted(item["source_counts"].items())),
                latest_seen=item["latest_seen"],
                highest_score=round_float(item["highest_score"]),
                review_statuses=sorted(item["review_statuses"]),
                notes=sorted(item["notes"]),
            )
        )
    return sorted(rows, key=lambda row: (row.priority, -(row.highest_score or -1), row.symbol))


def build_daily_ohlc_coverage_plan(
    rows: list[DailyOhlcUniverseRow],
    *,
    load_result: DailyOhlcLoadResult | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central().isoformat()
    covered = {record.symbol for record in (load_result.valid_records if load_result else [])}
    category_counts: dict[str, int] = {}
    for row in rows:
        for category in row.categories:
            category_counts[category] = category_counts.get(category, 0) + 1
    plan_rows = []
    for row in rows:
        payload = asdict(row)
        payload["covered"] = row.symbol in covered
        payload["needs_fetch"] = row.symbol not in covered
        plan_rows.append(payload)
    return {
        "schema_version": DAILY_OHLC_SCHEMA_VERSION,
        "engine_version": DAILY_OHLC_ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "summary": {
            "symbols": len(rows),
            "covered_symbols": len([row for row in rows if row.symbol in covered]),
            "missing_symbols": len([row for row in rows if row.symbol not in covered]),
            "priority_1_symbols": len([row for row in rows if row.priority == 1]),
            "priority_2_symbols": len([row for row in rows if row.priority == 2]),
            "priority_3_symbols": len([row for row in rows if row.priority == 3]),
            "baseline_symbols": len([row for row in rows if row.priority == 0]),
        },
        "category_counts": dict(sorted(category_counts.items())),
        "priority_order": [
            "Priority 1: alerts, outcomes, current watchlist, entry plans, active monitor targets.",
            "Priority 2: recent high-score captures, Candidate Story symbols, repeated captures, reviewed candidates.",
            "Priority 3: broader research candidates and recent captures.",
            "Baselines: QQQ, SPY, SMH, SOXX are always requested.",
        ],
        "rows": plan_rows,
        "guardrails": [
            "Research-only cache plan; no trade recommendations.",
            "Do not infer missing data or mutate source evidence.",
            "Daily OHLC cache remains additive and file-based.",
        ],
    }


def write_daily_ohlc_coverage_plan(
    plan: dict[str, Any],
    *,
    json_path: Path = DAILY_OHLC_COVERAGE_PLAN_LATEST_JSON,
    markdown_path: Path = DAILY_OHLC_COVERAGE_PLAN_LATEST_MD,
) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    write_daily_ohlc_coverage_plan_markdown(plan, markdown_path)
    return {"json": json_path, "markdown": markdown_path}


def write_daily_ohlc_coverage_plan_markdown(plan: dict[str, Any], path: Path) -> Path:
    summary = plan["summary"]
    lines = [
        f"# Daily OHLC Coverage Plan - {plan['generated_at']}",
        "",
        "Research-only priority plan for daily OHLC breakout coverage. This does not change scoring, readiness, alerts, scanner behavior, trade planning, outcomes, broker behavior, or UI workflow.",
        "",
        "## Summary",
        "",
        f"- Symbols: {summary['symbols']}",
        f"- Covered symbols: {summary['covered_symbols']}",
        f"- Missing symbols: {summary['missing_symbols']}",
        f"- Baseline symbols: {summary['baseline_symbols']}",
        f"- Priority 1 symbols: {summary['priority_1_symbols']}",
        f"- Priority 2 symbols: {summary['priority_2_symbols']}",
        f"- Priority 3 symbols: {summary['priority_3_symbols']}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in plan.get("category_counts", {}).items():
        lines.append(f"- {category}: {count}")
    lines.extend(["", "## Priority Rows", ""])
    rows = plan.get("rows", [])
    if rows:
        lines.extend(
            [
                "| Priority | Symbol | Covered | Categories | Highest Score | Latest Seen |",
                "| ---: | --- | --- | --- | ---: | --- |",
            ]
        )
        for row in rows[:250]:
            lines.append(
                f"| {row['priority']} | {row['symbol']} | {row['covered']} | "
                f"{', '.join(row.get('categories') or [])} | {format_report_value(row.get('highest_score'))} | "
                f"{row.get('latest_seen') or ''} |"
            )
    else:
        lines.append("- No symbols found.")
    lines.extend(["", "## Guardrails", ""])
    lines.extend([f"- {item}" for item in plan.get("guardrails", [])])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_daily_ohlc_records(
    path: Path = DAILY_OHLC_SOURCE_PATH,
    *,
    requested_symbols: list[str] | None = None,
    generated_at: str | None = None,
) -> DailyOhlcLoadResult:
    generated_at = generated_at or now_central().isoformat()
    requested = sorted({symbol.upper().strip() for symbol in (requested_symbols or []) if symbol.strip()})
    if not path.exists():
        return DailyOhlcLoadResult(
            source_path=str(path),
            generated_at=generated_at,
            records=[],
            valid_records=[],
            invalid_records=[],
            missing_symbols=requested,
            warnings=[f"DAILY_OHLC_SOURCE_MISSING:{path}"],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return DailyOhlcLoadResult(
            source_path=str(path),
            generated_at=generated_at,
            records=[],
            valid_records=[],
            invalid_records=[],
            missing_symbols=requested,
            warnings=[f"DAILY_OHLC_SOURCE_UNREADABLE:{type(exc).__name__}"],
        )
    records = normalize_daily_ohlc_payload(payload, imported_at=generated_at)
    valid = [record for record in records if record.quality_status == QUALITY_VALID]
    invalid = [record for record in records if record.quality_status != QUALITY_VALID]
    covered = {record.symbol for record in valid}
    missing = [symbol for symbol in requested if symbol not in covered]
    warnings: list[str] = []
    if invalid:
        warnings.append(f"INVALID_DAILY_OHLC_RECORDS:{len(invalid)}")
    if missing:
        warnings.append(f"MISSING_DAILY_OHLC_SYMBOLS:{len(missing)}")
    return DailyOhlcLoadResult(
        source_path=str(path),
        generated_at=generated_at,
        records=records,
        valid_records=valid,
        invalid_records=invalid,
        missing_symbols=missing,
        warnings=warnings,
    )


def normalize_daily_ohlc_payload(payload: Any, *, imported_at: str) -> list[DailyOhlcRecord]:
    raw_records: list[Any] = []
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        raw_records = payload["records"]
    elif isinstance(payload, dict) and isinstance(payload.get("bars"), dict):
        for symbol, items in payload["bars"].items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    raw = dict(item)
                    raw.setdefault("symbol", symbol)
                    raw_records.append(raw)
    elif isinstance(payload, list):
        raw_records = payload
    return [record_from_payload(item, imported_at=imported_at) for item in raw_records if isinstance(item, dict)]


def record_from_payload(payload: dict[str, Any], *, imported_at: str) -> DailyOhlcRecord:
    symbol = str(payload.get("symbol") or "").upper().strip()
    date_text = str(payload.get("date") or payload.get("day") or payload.get("timestamp") or "").strip()[:10]
    open_value = parse_float(payload.get("open"))
    high = parse_float(payload.get("high"))
    low = parse_float(payload.get("low"))
    close = parse_float(payload.get("close"))
    volume = parse_int(payload.get("volume"))
    adjusted = parse_optional_bool(payload.get("adjusted"))
    source = str(payload.get("source") or "daily_ohlc_local").strip()
    warnings = validate_daily_ohlc_values(
        symbol=symbol,
        date_text=date_text,
        open_value=open_value,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    return DailyOhlcRecord(
        symbol=symbol,
        date=date_text,
        open=round_float(open_value),
        high=round_float(high),
        low=round_float(low),
        close=round_float(close),
        volume=volume,
        source=source,
        adjusted=adjusted,
        imported_at=str(payload.get("imported_at") or payload.get("generated_at") or imported_at),
        quality_status=QUALITY_VALID if not warnings else QUALITY_INVALID,
        warnings=warnings,
    )


def validate_daily_ohlc_values(
    *,
    symbol: str,
    date_text: str,
    open_value: float | None,
    high: float | None,
    low: float | None,
    close: float | None,
    volume: int | None,
) -> list[str]:
    warnings: list[str] = []
    if not symbol:
        warnings.append("MISSING_SYMBOL")
    try:
        datetime.fromisoformat(date_text)
    except ValueError:
        warnings.append("INVALID_DATE")
    values = {"open": open_value, "high": high, "low": low, "close": close}
    for field_name, value in values.items():
        if value is None:
            warnings.append(f"MISSING_{field_name.upper()}")
        elif value <= 0:
            warnings.append(f"NON_POSITIVE_{field_name.upper()}")
    if volume is not None and volume < 0:
        warnings.append("NEGATIVE_VOLUME")
    if all(value is not None for value in values.values()):
        assert open_value is not None and high is not None and low is not None and close is not None
        if high < max(open_value, close, low):
            warnings.append("IMPOSSIBLE_HIGH")
        if low > min(open_value, close, high):
            warnings.append("IMPOSSIBLE_LOW")
    return warnings


def write_daily_ohlc_cache(
    records: list[DailyOhlcRecord],
    *,
    path: Path = DAILY_OHLC_SOURCE_PATH,
    generated_at: str | None = None,
) -> Path:
    ensure_app_dirs()
    generated_at = generated_at or now_central().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    valid_records = [record for record in records if record.quality_status == QUALITY_VALID]
    payload = {
        "schema_version": DAILY_OHLC_SCHEMA_VERSION,
        "engine_version": DAILY_OHLC_ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "records": [asdict(record) for record in sorted(valid_records, key=lambda item: (item.symbol, item.date))],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def expand_daily_ohlc_cache(
    universe_rows: list[DailyOhlcUniverseRow],
    *,
    cache_path: Path = DAILY_OHLC_SOURCE_PATH,
    generated_at: str | None = None,
    session: requests.Session | None = None,
    lookback_days: int = 460,
    retry_limit: int = 1,
    delay_seconds: float = 0.15,
    max_symbols: int | None = None,
    refresh_existing: bool = False,
) -> DailyOhlcExpansionResult:
    generated_at = generated_at or now_central().isoformat()
    existing = load_daily_ohlc_records(cache_path, generated_at=generated_at)
    existing_by_symbol = {record.symbol for record in existing.valid_records}
    requested = [row.symbol for row in universe_rows]
    candidates = [
        row.symbol
        for row in universe_rows
        if refresh_existing or row.symbol not in existing_by_symbol
    ]
    if max_symbols is not None:
        candidates = candidates[:max_symbols]
    http = session or build_http_session()
    fetched_records: list[DailyOhlcRecord] = []
    failed_symbols: list[str] = []
    warnings: list[str] = []
    for index, symbol in enumerate(candidates):
        records: list[DailyOhlcRecord] = []
        for attempt in range(retry_limit + 1):
            records = fetch_yahoo_daily_ohlc(http, symbol, generated_at=generated_at, lookback_days=lookback_days)
            if any(record.quality_status == QUALITY_VALID for record in records):
                break
            if attempt < retry_limit and delay_seconds > 0:
                time.sleep(delay_seconds)
        valid_count = sum(1 for record in records if record.quality_status == QUALITY_VALID)
        if valid_count:
            fetched_records.extend(records)
        else:
            failed_symbols.append(symbol)
            if records:
                reasons = sorted({warning for record in records for warning in record.warnings})
                warnings.append(f"FETCH_FAILED:{symbol}:{','.join(reasons) if reasons else 'NO_VALID_RECORDS'}")
            else:
                warnings.append(f"FETCH_FAILED:{symbol}:NO_RECORDS")
        if delay_seconds > 0 and index < len(candidates) - 1:
            time.sleep(delay_seconds)
    merged = merge_daily_ohlc_records(existing.valid_records + fetched_records)
    invalid_records = [record for record in existing.invalid_records + fetched_records if record.quality_status != QUALITY_VALID]
    write_daily_ohlc_cache(merged, path=cache_path, generated_at=generated_at)
    return DailyOhlcExpansionResult(
        generated_at=generated_at,
        requested_symbols=requested,
        fetched_symbols=sorted({record.symbol for record in fetched_records if record.quality_status == QUALITY_VALID}),
        skipped_symbols=sorted([symbol for symbol in requested if symbol in existing_by_symbol and symbol not in candidates]),
        failed_symbols=failed_symbols,
        existing_records=len(existing.valid_records),
        fetched_records=sum(1 for record in fetched_records if record.quality_status == QUALITY_VALID),
        final_valid_records=len(merged),
        invalid_records=len(invalid_records),
        cache_path=str(cache_path),
        warnings=dedupe(warnings),
    )


def merge_daily_ohlc_records(records: list[DailyOhlcRecord]) -> list[DailyOhlcRecord]:
    by_key: dict[tuple[str, str], DailyOhlcRecord] = {}
    for record in records:
        if record.quality_status != QUALITY_VALID:
            continue
        by_key[(record.symbol, record.date)] = record
    return sorted(by_key.values(), key=lambda record: (record.symbol, record.date))


def fetch_yahoo_daily_ohlc(
    session: requests.Session,
    symbol: str,
    *,
    generated_at: str | None = None,
    lookback_days: int = 460,
) -> list[DailyOhlcRecord]:
    generated_at = generated_at or now_central().isoformat()
    symbol = symbol.upper().strip()
    if not symbol:
        return []
    yahoo_symbol = symbol.replace(".", "-")
    period1 = int((datetime.now() - timedelta(days=lookback_days)).timestamp())
    period2 = int((datetime.now() + timedelta(days=3)).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )
    try:
        response = session.get(url, timeout=20)
    except requests.RequestException:
        return [
            DailyOhlcRecord(
                symbol=symbol,
                date="",
                open=None,
                high=None,
                low=None,
                close=None,
                volume=None,
                source="yahoo_chart_1d_adjusted",
                adjusted=True,
                imported_at=generated_at,
                quality_status=QUALITY_INVALID,
                warnings=["YAHOO_CHART_REQUEST_FAILED"],
            )
        ]
    if response.status_code != 200:
        return [
            DailyOhlcRecord(
                symbol=symbol,
                date="",
                open=None,
                high=None,
                low=None,
                close=None,
                volume=None,
                source="yahoo_chart_1d_adjusted",
                adjusted=True,
                imported_at=generated_at,
                quality_status=QUALITY_INVALID,
                warnings=[f"YAHOO_CHART_HTTP_{response.status_code}"],
            )
        ]
    try:
        payload = response.json()
    except ValueError:
        return [
            DailyOhlcRecord(
                symbol=symbol,
                date="",
                open=None,
                high=None,
                low=None,
                close=None,
                volume=None,
                source="yahoo_chart_1d_adjusted",
                adjusted=True,
                imported_at=generated_at,
                quality_status=QUALITY_INVALID,
                warnings=["YAHOO_CHART_INVALID_JSON"],
            )
        ]
    return parse_yahoo_chart_daily_ohlc(payload, symbol=symbol, imported_at=generated_at)


def parse_yahoo_chart_daily_ohlc(payload: dict[str, Any], *, symbol: str, imported_at: str) -> list[DailyOhlcRecord]:
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return [
            DailyOhlcRecord(
                symbol=symbol,
                date="",
                open=None,
                high=None,
                low=None,
                close=None,
                volume=None,
                source="yahoo_chart_1d_adjusted",
                adjusted=True,
                imported_at=imported_at,
                quality_status=QUALITY_INVALID,
                warnings=["YAHOO_CHART_EMPTY"],
            )
        ]
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = (item.get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (item.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    records: list[DailyOhlcRecord] = []
    for index, timestamp in enumerate(timestamps):
        raw = {
            "symbol": symbol,
            "date": datetime.fromtimestamp(timestamp).date().isoformat(),
            "source": "yahoo_chart_1d_adjusted",
            "adjusted": True,
            "imported_at": imported_at,
        }
        try:
            raw_open = value_at(quote.get("open") or [], index)
            raw_high = value_at(quote.get("high") or [], index)
            raw_low = value_at(quote.get("low") or [], index)
            raw_close = value_at(quote.get("close") or [], index)
            raw_volume = value_at(quote.get("volume") or [], index)
            adjusted_close = value_at(adjclose, index) if adjclose else raw_close
        except IndexError:
            continue
        if None in (raw_open, raw_high, raw_low, raw_close, adjusted_close):
            continue
        ratio = float(adjusted_close) / float(raw_close) if raw_close else 1.0
        raw.update(
            {
                "open": float(raw_open) * ratio,
                "high": float(raw_high) * ratio,
                "low": float(raw_low) * ratio,
                "close": float(adjusted_close),
                "volume": raw_volume,
            }
        )
        records.append(record_from_payload(raw, imported_at=imported_at))
    return records


def fetch_yahoo_daily_ohlc_for_symbols(
    symbols: list[str],
    *,
    generated_at: str | None = None,
    session: requests.Session | None = None,
    lookback_days: int = 460,
) -> list[DailyOhlcRecord]:
    generated_at = generated_at or now_central().isoformat()
    session = session or build_http_session()
    records: list[DailyOhlcRecord] = []
    for symbol in sorted({item.upper().strip() for item in symbols if item.strip()}):
        records.extend(fetch_yahoo_daily_ohlc(session, symbol, generated_at=generated_at, lookback_days=lookback_days))
    return records


def build_daily_ohlc_coverage_report(
    load_result: DailyOhlcLoadResult,
    *,
    requested_symbols: list[str] | None = None,
    universe_rows: list[DailyOhlcUniverseRow] | None = None,
    failed_symbols: list[str] | None = None,
    minimum_history_bars: int = 50,
) -> dict[str, Any]:
    requested = sorted({symbol.upper().strip() for symbol in (requested_symbols or []) if symbol.strip()})
    by_symbol: dict[str, list[DailyOhlcRecord]] = {}
    for record in load_result.valid_records:
        by_symbol.setdefault(record.symbol, []).append(record)
    symbol_rows: list[dict[str, Any]] = []
    insufficient_history: list[str] = []
    for symbol, records in sorted(by_symbol.items()):
        records = sorted(records, key=lambda record: record.date)
        warnings: list[str] = []
        if len(records) < minimum_history_bars:
            warnings.append(f"INSUFFICIENT_HISTORY:{len(records)}/{minimum_history_bars}")
            insufficient_history.append(symbol)
        symbol_rows.append(
            {
                "symbol": symbol,
                "bar_count": len(records),
                "first_date": records[0].date if records else "",
                "latest_date": records[-1].date if records else "",
                "source": records[-1].source if records else "",
                "adjusted": records[-1].adjusted if records else None,
                "warnings": warnings,
            }
        )
    missing_symbols = load_result.missing_symbols
    if requested and not missing_symbols:
        missing_symbols = [symbol for symbol in requested if symbol not in by_symbol]
    failed_symbols = sorted({normalize_symbol(symbol) for symbol in (failed_symbols or []) if normalize_symbol(symbol)})
    earliest = min((record.date for record in load_result.valid_records), default="")
    latest = max((record.date for record in load_result.valid_records), default="")
    category_coverage = coverage_by_category(universe_rows or [], covered_symbols=set(by_symbol))
    covered_requested_symbols = [symbol for symbol in requested if symbol in by_symbol] if requested else list(by_symbol)
    coverage_pct = round(len(covered_requested_symbols) / len(requested) * 100.0, 2) if requested else 0.0
    return {
        "schema_version": DAILY_OHLC_SCHEMA_VERSION,
        "engine_version": DAILY_OHLC_ENGINE_VERSION,
        "generated_at": load_result.generated_at,
        "research_only": True,
        "source_path": load_result.source_path,
        "summary": {
            "requested_symbols": len(requested),
            "covered_symbols": len(covered_requested_symbols),
            "coverage_pct": coverage_pct,
            "valid_records": len(load_result.valid_records),
            "invalid_records": len(load_result.invalid_records),
            "missing_symbols": len(missing_symbols),
            "failed_symbols": len(failed_symbols),
            "insufficient_history_symbols": len(insufficient_history),
            "earliest_date": earliest,
            "latest_date": latest,
        },
        "coverage_by_category": category_coverage,
        "symbols": symbol_rows,
        "missing_symbols": missing_symbols,
        "failed_symbols": failed_symbols,
        "invalid_records": [asdict(record) for record in load_result.invalid_records[:100]],
        "warnings": dedupe(
            load_result.warnings
            + ([f"FAILED_DAILY_OHLC_SYMBOLS:{len(failed_symbols)}"] if failed_symbols else [])
            + ([f"INSUFFICIENT_HISTORY_SYMBOLS:{len(insufficient_history)}"] if insufficient_history else [])
        ),
        "next_recommended_action": next_coverage_action(missing_symbols=missing_symbols, failed_symbols=failed_symbols),
    }


def write_daily_ohlc_coverage_report(
    report: dict[str, Any],
    *,
    json_path: Path = DAILY_OHLC_COVERAGE_LATEST_JSON,
    markdown_path: Path = DAILY_OHLC_COVERAGE_LATEST_MD,
) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_daily_ohlc_coverage_markdown(report, markdown_path)
    return {"json": json_path, "markdown": markdown_path}


def write_daily_ohlc_coverage_markdown(report: dict[str, Any], path: Path) -> Path:
    summary = report["summary"]
    lines = [
        f"# Daily OHLC Coverage - {report['generated_at']}",
        "",
        "Research-only daily OHLC coverage report. This report does not change scanner, scoring, readiness, alerts, trade planning, outcomes, broker behavior, or UI workflows.",
        "",
        "## Summary",
        "",
        f"- Requested symbols: {summary['requested_symbols']}",
        f"- Covered symbols: {summary['covered_symbols']}",
        f"- Coverage: {summary.get('coverage_pct', 0)}%",
        f"- Valid records: {summary['valid_records']}",
        f"- Invalid records: {summary['invalid_records']}",
        f"- Missing symbols: {summary['missing_symbols']}",
        f"- Failed symbols: {summary.get('failed_symbols', 0)}",
        f"- Insufficient-history symbols: {summary['insufficient_history_symbols']}",
        f"- Earliest date: {summary.get('earliest_date') or 'n/a'}",
        f"- Latest date: {summary.get('latest_date') or 'n/a'}",
        "",
        "## Coverage By Category",
        "",
    ]
    category_rows = report.get("coverage_by_category", [])
    if category_rows:
        lines.extend(
            [
                "| Category | Requested | Covered | Coverage % |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in category_rows:
            lines.append(
                f"| {row['category']} | {row['requested_symbols']} | {row['covered_symbols']} | {row['coverage_pct']} |"
            )
    else:
        lines.append("- No category coverage data.")
    lines.extend(
        [
            "",
        "## Symbol Coverage",
        "",
        ]
    )
    rows = report.get("symbols", [])
    if rows:
        lines.extend(
            [
                "| Symbol | Bars | First Date | Latest Date | Source | Adjusted | Warnings |",
                "| --- | ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            warnings = ", ".join(row.get("warnings") or []) or "None"
            lines.append(
                f"| {row['symbol']} | {row['bar_count']} | {row['first_date']} | {row['latest_date']} | "
                f"{row['source']} | {row['adjusted']} | {warnings} |"
            )
    else:
        lines.append("- No covered symbols.")
    lines.extend(["", "## Missing Symbols", ""])
    missing = report.get("missing_symbols") or []
    lines.extend([f"- {symbol}" for symbol in missing[:100]] if missing else ["- None."])
    lines.extend(["", "## Failed Symbols", ""])
    failed = report.get("failed_symbols") or []
    lines.extend([f"- {symbol}" for symbol in failed[:100]] if failed else ["- None."])
    lines.extend(["", "## Warnings", ""])
    warnings = report.get("warnings") or []
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    lines.extend(["", "## Next Recommended Action", "", f"- {report.get('next_recommended_action') or 'None.'}"])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def coverage_by_category(rows: list[DailyOhlcUniverseRow], *, covered_symbols: set[str]) -> list[dict[str, Any]]:
    category_symbols: dict[str, set[str]] = {}
    for row in rows:
        for category in row.categories:
            category_symbols.setdefault(category, set()).add(row.symbol)
    output: list[dict[str, Any]] = []
    for category, symbols in sorted(category_symbols.items()):
        covered = symbols & covered_symbols
        output.append(
            {
                "category": category,
                "requested_symbols": len(symbols),
                "covered_symbols": len(covered),
                "coverage_pct": round(len(covered) / len(symbols) * 100.0, 2) if symbols else 0.0,
            }
        )
    return output


def next_coverage_action(*, missing_symbols: list[str], failed_symbols: list[str]) -> str:
    if failed_symbols:
        return "Review failed symbols for provider errors, bad tickers, or temporary rate limits before retrying."
    if missing_symbols:
        return "Run the explicit research-only cache expansion for remaining missing priority symbols."
    return "Coverage target satisfied for the requested universe; proceed with breakout research review."


def mirror_daily_ohlc_to_sqlite(records: list[DailyOhlcRecord], *, db_path: Path) -> int:
    valid = [record for record in records if record.quality_status == QUALITY_VALID]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_daily_ohlc (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER,
                source TEXT NOT NULL,
                adjusted INTEGER,
                imported_at TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                PRIMARY KEY (symbol, date, source)
            )
            """
        )
        connection.executemany(
            """
            INSERT OR REPLACE INTO research_daily_ohlc (
                symbol, date, open, high, low, close, volume, source, adjusted,
                imported_at, quality_status, warnings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.symbol,
                    record.date,
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.volume,
                    record.source,
                    None if record.adjusted is None else int(record.adjusted),
                    record.imported_at,
                    record.quality_status,
                    json.dumps(record.warnings),
                )
                for record in valid
            ],
        )
    return len(valid)


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return [dict(row) for row in csv.DictReader(file)]


def load_json_list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get(key, []) if isinstance(payload, dict) else payload
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def load_json_mapping(path: Path, key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping = payload.get(key, {}) if isinstance(payload, dict) else {}
    return {str(name): value for name, value in mapping.items() if isinstance(value, dict)} if isinstance(mapping, dict) else {}


def load_latest_watchlist_items(watchlist_dir: Path) -> list[dict[str, Any]]:
    files = sorted(watchlist_dir.glob("watchlist-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return []
    try:
        payload = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def load_latest_monitor_targets(reports_dir: Path) -> list[dict[str, Any]]:
    files = sorted(reports_dir.glob("opportunity-monitor-targets-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return []
    try:
        payload = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    targets = payload.get("targets", []) if isinstance(payload, dict) else []
    return [item for item in targets if isinstance(item, dict)] if isinstance(targets, list) else []


def recent_cutoff_date(latest_date: str, days: int) -> str | None:
    try:
        latest = datetime.fromisoformat(latest_date[:10])
    except ValueError:
        return None
    return (latest - timedelta(days=days)).date().isoformat()


def normalize_symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def format_report_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def symbols_from_existing_evidence(
    *,
    captures_path: Path = ANALYSIS_CAPTURES_PATH,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
) -> list[str]:
    symbols: set[str] = set()
    if captures_path.exists():
        with captures_path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
                if symbol:
                    symbols.add(symbol)
    if alerts_path.exists():
        try:
            payload = json.loads(alerts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        alerts = payload.get("alerts", []) if isinstance(payload, dict) else []
        for alert in alerts if isinstance(alerts, list) else []:
            if isinstance(alert, dict):
                symbol = str(alert.get("symbol") or "").upper().strip()
                if symbol:
                    symbols.add(symbol)
    if minute_bars_path.exists():
        try:
            payload = json.loads(minute_bars_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        bars = payload.get("bars", {}) if isinstance(payload, dict) else {}
        if isinstance(bars, dict):
            symbols.update(str(symbol).upper().strip() for symbol in bars if str(symbol).strip())
    return sorted(symbols)


def value_at(values: list[Any], index: int) -> Any:
    if index >= len(values):
        raise IndexError(index)
    return values[index]


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def parse_optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def round_float(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    for item in items:
        if item not in output:
            output.append(item)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build research-only daily OHLC coverage reports.")
    parser.add_argument("--source", type=Path, default=DAILY_OHLC_SOURCE_PATH)
    parser.add_argument("--coverage-json", type=Path, default=DAILY_OHLC_COVERAGE_LATEST_JSON)
    parser.add_argument("--coverage-md", type=Path, default=DAILY_OHLC_COVERAGE_LATEST_MD)
    parser.add_argument("--plan-json", type=Path, default=DAILY_OHLC_COVERAGE_PLAN_LATEST_JSON)
    parser.add_argument("--plan-md", type=Path, default=DAILY_OHLC_COVERAGE_PLAN_LATEST_MD)
    parser.add_argument("--fetch-symbol", action="append", default=[], help="Explicit symbol to fetch into the research cache.")
    parser.add_argument("--include-qqq", action="store_true", help="Include QQQ for relative-strength research.")
    parser.add_argument("--symbols-from-evidence", action="store_true", help="Use symbols already present in local evidence as requested coverage.")
    parser.add_argument("--fetch-requested", action="store_true", help="Fetch requested symbols into the local research cache.")
    parser.add_argument("--build-plan", action="store_true", help="Build the prioritized coverage universe from local evidence.")
    parser.add_argument("--expand-coverage", action="store_true", help="Fetch missing prioritized universe symbols into the research cache.")
    parser.add_argument("--lookback-days", type=int, default=460)
    parser.add_argument("--retry-limit", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args(argv)

    ensure_app_dirs()
    generated_at = now_central().isoformat()
    universe_rows: list[DailyOhlcUniverseRow] = []
    expansion: DailyOhlcExpansionResult | None = None
    if args.build_plan or args.expand_coverage:
        universe_rows = build_daily_ohlc_universe()
        requested = [row.symbol for row in universe_rows]
    else:
        requested = symbols_from_existing_evidence() if args.symbols_from_evidence else []
        requested.extend(args.fetch_symbol)
        if args.include_qqq:
            requested.append("QQQ")
        requested = sorted({symbol.upper().strip() for symbol in requested if symbol.strip()})
        universe_rows = [
            DailyOhlcUniverseRow(
                symbol=symbol,
                priority=0 if symbol in BASELINE_SYMBOLS else 3,
                categories=["broad_market_baseline" if symbol in {"QQQ", "SPY"} else "research_candidates"],
                source_counts={},
            )
            for symbol in requested
        ]

    if args.expand_coverage and universe_rows:
        expansion = expand_daily_ohlc_cache(
            universe_rows,
            cache_path=args.source,
            generated_at=generated_at,
            lookback_days=args.lookback_days,
            retry_limit=args.retry_limit,
            delay_seconds=args.delay_seconds,
            max_symbols=args.max_symbols,
            refresh_existing=args.refresh_existing,
        )
    elif args.fetch_requested and requested:
        records = fetch_yahoo_daily_ohlc_for_symbols(requested, generated_at=generated_at, lookback_days=args.lookback_days)
        write_daily_ohlc_cache(records, path=args.source, generated_at=generated_at)

    result = load_daily_ohlc_records(args.source, requested_symbols=requested, generated_at=generated_at)
    if args.build_plan or args.expand_coverage:
        plan = build_daily_ohlc_coverage_plan(universe_rows, load_result=result, generated_at=generated_at)
        plan_paths = write_daily_ohlc_coverage_plan(plan, json_path=args.plan_json, markdown_path=args.plan_md)
        for label, path in plan_paths.items():
            print(f"plan_{label}: {path}")
    report = build_daily_ohlc_coverage_report(
        result,
        requested_symbols=requested,
        universe_rows=universe_rows,
        failed_symbols=expansion.failed_symbols if expansion else [],
    )
    paths = write_daily_ohlc_coverage_report(report, json_path=args.coverage_json, markdown_path=args.coverage_md)
    for label, path in paths.items():
        print(f"{label}: {path}")
    if expansion:
        print(f"expanded_requested: {len(expansion.requested_symbols)}")
        print(f"expanded_fetched_symbols: {len(expansion.fetched_symbols)}")
        print(f"expanded_failed_symbols: {len(expansion.failed_symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
