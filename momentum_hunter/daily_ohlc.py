from __future__ import annotations

import argparse
import csv
import json
import sqlite3
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

QUALITY_VALID = "VALID"
QUALITY_INVALID = "INVALID"
QUALITY_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


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
    return {
        "schema_version": DAILY_OHLC_SCHEMA_VERSION,
        "engine_version": DAILY_OHLC_ENGINE_VERSION,
        "generated_at": load_result.generated_at,
        "research_only": True,
        "source_path": load_result.source_path,
        "summary": {
            "requested_symbols": len(requested),
            "covered_symbols": len(by_symbol),
            "valid_records": len(load_result.valid_records),
            "invalid_records": len(load_result.invalid_records),
            "missing_symbols": len(missing_symbols),
            "insufficient_history_symbols": len(insufficient_history),
        },
        "symbols": symbol_rows,
        "missing_symbols": missing_symbols,
        "invalid_records": [asdict(record) for record in load_result.invalid_records[:100]],
        "warnings": dedupe(load_result.warnings + [f"INSUFFICIENT_HISTORY_SYMBOLS:{len(insufficient_history)}"] if insufficient_history else load_result.warnings),
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
        f"- Valid records: {summary['valid_records']}",
        f"- Invalid records: {summary['invalid_records']}",
        f"- Missing symbols: {summary['missing_symbols']}",
        f"- Insufficient-history symbols: {summary['insufficient_history_symbols']}",
        "",
        "## Symbol Coverage",
        "",
    ]
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
    lines.extend(["", "## Warnings", ""])
    warnings = report.get("warnings") or []
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
    parser.add_argument("--fetch-symbol", action="append", default=[], help="Explicit symbol to fetch into the research cache.")
    parser.add_argument("--include-qqq", action="store_true", help="Include QQQ for relative-strength research.")
    parser.add_argument("--symbols-from-evidence", action="store_true", help="Use symbols already present in local evidence as requested coverage.")
    parser.add_argument("--fetch-requested", action="store_true", help="Fetch requested symbols into the local research cache.")
    parser.add_argument("--lookback-days", type=int, default=460)
    args = parser.parse_args(argv)

    ensure_app_dirs()
    requested = symbols_from_existing_evidence() if args.symbols_from_evidence else []
    requested.extend(args.fetch_symbol)
    if args.include_qqq:
        requested.append("QQQ")
    requested = sorted({symbol.upper().strip() for symbol in requested if symbol.strip()})

    if args.fetch_requested and requested:
        generated_at = now_central().isoformat()
        records = fetch_yahoo_daily_ohlc_for_symbols(requested, generated_at=generated_at, lookback_days=args.lookback_days)
        write_daily_ohlc_cache(records, path=args.source, generated_at=generated_at)

    result = load_daily_ohlc_records(args.source, requested_symbols=requested)
    report = build_daily_ohlc_coverage_report(result, requested_symbols=requested)
    paths = write_daily_ohlc_coverage_report(report, json_path=args.coverage_json, markdown_path=args.coverage_md)
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
