from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH, load_minute_bars
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.market_tape_health import (
    MarketTapeHealthAttempt,
    MarketTapeHealthReport,
    build_market_tape_health_report,
)
from momentum_hunter.monitor_targets import build_monitor_target_report
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.time_utils import now_central


DATA_QUALITY_SCHEMA_VERSION = 1
DATA_QUALITY_ENGINE_VERSION = "data_quality_audit_v1"
DATA_QUALITY_LATEST_JSON = DATA_DIR / "reports" / "data-quality-latest.json"
DATA_QUALITY_LATEST_MD = DATA_DIR / "reports" / "data-quality-latest.md"
SCANNER_FIELDS = ["price", "percent_change", "volume", "relative_volume", "market_cap"]
TAPE_FIELDS = [
    "last_price",
    "bid",
    "ask",
    "spread_percent",
    "premarket_volume",
    "intraday_volume",
    "average_daily_volume_20",
    "relative_volume",
    "rvol_numerator",
    "rvol_denominator",
]


@dataclass(frozen=True)
class DataQualitySymbol:
    symbol: str
    usable_market_tape: bool
    best_provider: str = ""
    providers_attempted: list[str] = field(default_factory=list)
    fields_returned: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_percent: float | None = None
    relative_volume: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DataQualityReport:
    generated_at: str
    symbols: list[str]
    symbol_count: int
    usable_market_tape_count: int
    missing_market_tape_count: int
    provider_summary: dict[str, dict[str, int]]
    symbol_rows: list[DataQualitySymbol]
    field_summary: dict[str, dict[str, int]]
    timestamp_summary: dict[str, Any]
    scanner_field_reliability: dict[str, dict[str, int]]
    capture_summary: dict[str, Any]
    minute_bar_coverage: dict[str, Any]
    duplicate_capture_anomalies: list[dict[str, Any]]
    repeated_ticker_anomalies: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def build_data_quality_report(
    symbols: list[str] | None = None,
    *,
    market_tape_report: MarketTapeHealthReport | None = None,
    captures_dir: Path = CAPTURES_DIR,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    generated_at: datetime | None = None,
) -> DataQualityReport:
    generated_at = generated_at or now_central()
    clean_symbols = normalize_symbols(symbols or default_symbols())
    if market_tape_report is None and clean_symbols:
        market_tape_report = build_market_tape_health_report(clean_symbols, generated_at=generated_at)

    attempts = market_tape_report.attempts if market_tape_report else []
    symbol_rows = build_symbol_rows(clean_symbols, attempts)
    capture_rows = load_capture_candidate_rows(captures_dir)
    field_summary = tape_field_summary(attempts)
    scanner_reliability = scanner_field_reliability(capture_rows)
    duplicate_anomalies = duplicate_tickers_within_captures(capture_rows)
    repeated_anomalies = repeated_identical_candidate_rows(capture_rows)
    minute_coverage = minute_bar_coverage(clean_symbols, minute_bars_path)
    usable_count = sum(1 for row in symbol_rows if row.usable_market_tape)
    warnings = build_warnings(
        symbols=clean_symbols,
        usable_count=usable_count,
        field_summary=field_summary,
        scanner_reliability=scanner_reliability,
        duplicate_anomalies=duplicate_anomalies,
        repeated_anomalies=repeated_anomalies,
        minute_coverage=minute_coverage,
        market_tape_report=market_tape_report,
    )
    return DataQualityReport(
        generated_at=generated_at.isoformat(),
        symbols=clean_symbols,
        symbol_count=len(clean_symbols),
        usable_market_tape_count=usable_count,
        missing_market_tape_count=max(0, len(clean_symbols) - usable_count),
        provider_summary=market_tape_report.provider_summary if market_tape_report else {},
        symbol_rows=symbol_rows,
        field_summary=field_summary,
        timestamp_summary=timestamp_summary(clean_symbols),
        scanner_field_reliability=scanner_reliability,
        capture_summary=capture_summary(capture_rows),
        minute_bar_coverage=minute_coverage,
        duplicate_capture_anomalies=duplicate_anomalies,
        repeated_ticker_anomalies=repeated_anomalies,
        warnings=warnings,
    )


def default_symbols(limit: int = 5) -> list[str]:
    symbols: list[str] = []
    try:
        target_report = build_monitor_target_report()
        symbols.extend(target.symbol for target in target_report.targets)
    except Exception:
        pass
    if not symbols:
        rows = load_capture_candidate_rows(CAPTURES_DIR)
        latest_capture_time = max((row.get("capture_time", "") for row in rows), default="")
        symbols.extend(str(row.get("ticker", "")) for row in rows if row.get("capture_time") == latest_capture_time)
    return normalize_symbols(symbols)[:limit]


def build_symbol_rows(symbols: list[str], attempts: list[MarketTapeHealthAttempt]) -> list[DataQualitySymbol]:
    attempts_by_symbol: dict[str, list[MarketTapeHealthAttempt]] = {}
    for attempt in attempts:
        attempts_by_symbol.setdefault(attempt.symbol, []).append(attempt)
    rows: list[DataQualitySymbol] = []
    for symbol in symbols:
        symbol_attempts = attempts_by_symbol.get(symbol, [])
        combined = next((attempt for attempt in symbol_attempts if attempt.provider == "combined"), None)
        best = next((attempt for attempt in symbol_attempts if attempt.usable_for_alerting), None)
        source = combined or best
        returned = sorted(set(source.fields_returned if source else []))
        missing = [field for field in TAPE_FIELDS if field not in returned]
        provider_errors = dedupe(
            [attempt.error_message for attempt in symbol_attempts if attempt.error_message]
        )
        warnings = dedupe(
            [warning for attempt in symbol_attempts for warning in attempt.warnings]
        )
        if not (combined and combined.usable_for_alerting):
            warnings.append("NO_USABLE_COMBINED_TAPE")
        rows.append(
            DataQualitySymbol(
                symbol=symbol,
                usable_market_tape=bool(combined and combined.usable_for_alerting),
                best_provider=(best.provider if best else ""),
                providers_attempted=[attempt.provider for attempt in symbol_attempts],
                fields_returned=returned,
                missing_fields=missing,
                provider_errors=provider_errors,
                last_price=source.last_price if source else None,
                bid=source.bid if source else None,
                ask=source.ask if source else None,
                spread_percent=source.spread_percent if source else None,
                relative_volume=source.relative_volume if source else None,
                warnings=dedupe(warnings),
            )
        )
    return rows


def tape_field_summary(attempts: list[MarketTapeHealthAttempt]) -> dict[str, dict[str, int]]:
    combined = [attempt for attempt in attempts if attempt.provider == "combined"]
    summary: dict[str, dict[str, int]] = {}
    for field_name in TAPE_FIELDS:
        available = 0
        invalid = 0
        for attempt in combined:
            value = getattr(attempt, field_name)
            if value is not None:
                available += 1
            if impossible_tape_value(field_name, value):
                invalid += 1
        summary[field_name] = {
            "available": available,
            "missing": max(0, len(combined) - available),
            "invalid_or_impossible": invalid,
        }
    bid_ask_invalid = sum(
        1
        for attempt in combined
        if attempt.bid is not None and attempt.ask is not None and attempt.bid > attempt.ask
    )
    summary["bid_ask_order"] = {
        "available": sum(1 for attempt in combined if attempt.bid is not None and attempt.ask is not None),
        "missing": sum(1 for attempt in combined if attempt.bid is None or attempt.ask is None),
        "invalid_or_impossible": bid_ask_invalid,
    }
    return summary


def scanner_field_reliability(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for field_name in SCANNER_FIELDS:
        present = 0
        zero = 0
        missing = 0
        for row in rows:
            value = row.get(field_name)
            if value in (None, ""):
                missing += 1
                continue
            present += 1
            if value == 0 or value == 0.0:
                zero += 1
        summary[field_name] = {
            "present": present,
            "missing": missing,
            "zero": zero,
            "total_rows": len(rows),
        }
    return summary


def load_capture_candidate_rows(captures_dir: Path) -> list[dict[str, Any]]:
    if not captures_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(captures_dir.glob("*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        capture_time = str(payload.get("capture_time", ""))
        session = str(payload.get("capture_session") or payload.get("session") or "")
        scanner = payload.get("scanner", {})
        scanner_name = scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            row = dict(candidate)
            row.update(
                {
                    "capture_path": str(path),
                    "capture_time": capture_time,
                    "capture_session": session,
                    "capture_scanner": scanner_name,
                    "capture_rank": index + 1,
                }
            )
            rows.append(row)
    return rows


def capture_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    capture_paths = sorted({str(row.get("capture_path", "")) for row in rows if row.get("capture_path")})
    sessions: dict[str, int] = {}
    for row in rows:
        session = str(row.get("capture_session") or "unknown")
        sessions[session] = sessions.get(session, 0) + 1
    return {
        "capture_file_count": len(capture_paths),
        "candidate_row_count": len(rows),
        "sessions": sessions,
    }


def duplicate_tickers_within_captures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        ticker = normalize_symbol(row.get("ticker"))
        if not ticker:
            continue
        grouped.setdefault((str(row.get("capture_path", "")), ticker), []).append(row)
    anomalies = []
    for (capture_path, ticker), items in sorted(grouped.items()):
        if len(items) > 1:
            anomalies.append(
                {
                    "capture_path": capture_path,
                    "ticker": ticker,
                    "count": len(items),
                    "ranks": [item.get("capture_rank") for item in items],
                }
            )
    return anomalies


def repeated_identical_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        ticker = normalize_symbol(row.get("ticker"))
        if not ticker:
            continue
        key = (
            ticker,
            row.get("price"),
            row.get("volume"),
            row.get("score"),
            row.get("percent_change"),
            row.get("relative_volume"),
        )
        grouped.setdefault(key, []).append(row)
    anomalies = []
    for key, items in sorted(grouped.items(), key=lambda pair: (str(pair[0][0]), -len(pair[1]))):
        if len(items) < 2:
            continue
        anomalies.append(
            {
                "ticker": key[0],
                "price": key[1],
                "volume": key[2],
                "score": key[3],
                "percent_change": key[4],
                "relative_volume": key[5],
                "repeat_count": len(items),
                "captures": [item.get("capture_path") for item in items[:10]],
            }
        )
    return anomalies[:50]


def minute_bar_coverage(symbols: list[str], minute_bars_path: Path) -> dict[str, Any]:
    bars = load_minute_bars(minute_bars_path)
    rows = {
        symbol: {
            "bar_count": len(bars.get(symbol, [])),
            "has_bars": bool(bars.get(symbol)),
        }
        for symbol in symbols
    }
    return {
        "source_path": str(minute_bars_path),
        "symbols_with_bars": sum(1 for item in rows.values() if item["has_bars"]),
        "symbols_missing_bars": sum(1 for item in rows.values() if not item["has_bars"]),
        "symbols": rows,
    }


def timestamp_summary(symbols: list[str]) -> dict[str, Any]:
    return {
        "source_timestamp_supported": False,
        "known_timestamp_count": 0,
        "unknown_timestamp_count": len(symbols),
        "stale_timestamp_count": 0,
        "invalid_timestamp_count": 0,
        "note": (
            "MarketTape does not currently normalize provider quote timestamps; "
            "stale quote detection is therefore unknown, not assumed fresh."
        ),
    }


def build_warnings(
    *,
    symbols: list[str],
    usable_count: int,
    field_summary: dict[str, dict[str, int]],
    scanner_reliability: dict[str, dict[str, int]],
    duplicate_anomalies: list[dict[str, Any]],
    repeated_anomalies: list[dict[str, Any]],
    minute_coverage: dict[str, Any],
    market_tape_report: MarketTapeHealthReport | None,
) -> list[str]:
    warnings: list[str] = []
    if not symbols:
        warnings.append("NO_SYMBOLS_AVAILABLE_FOR_DATA_QUALITY_AUDIT")
    elif usable_count < len(symbols):
        warnings.append("SYMBOLS_WITHOUT_USABLE_MARKET_TAPE")
    if market_tape_report:
        warnings.extend(market_tape_report.warnings)
    if symbols:
        warnings.append("MARKET_TAPE_TIMESTAMP_UNAVAILABLE")
    for field_name in ["bid", "ask", "spread_percent", "relative_volume"]:
        row = field_summary.get(field_name, {})
        if row.get("missing", 0):
            warnings.append(f"MISSING_TAPE_FIELD:{field_name}")
    relvol = scanner_reliability.get("relative_volume", {})
    if relvol.get("missing", 0) or relvol.get("zero", 0):
        warnings.append("SCANNER_RELATIVE_VOLUME_GAPS")
    if duplicate_anomalies:
        warnings.append("DUPLICATE_TICKERS_WITHIN_CAPTURE")
    if repeated_anomalies:
        warnings.append("REPEATED_IDENTICAL_CANDIDATE_ROWS")
    if minute_coverage.get("symbols_missing_bars", 0):
        warnings.append("SYMBOLS_WITHOUT_MINUTE_BAR_COVERAGE")
    return dedupe(warnings)


def export_data_quality_report(
    report: DataQualityReport,
    *,
    json_path: Path = DATA_QUALITY_LATEST_JSON,
    markdown_path: Path = DATA_QUALITY_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DATA_QUALITY_SCHEMA_VERSION,
        "engine_version": DATA_QUALITY_ENGINE_VERSION,
        "report": asdict(report),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_data_quality_markdown(report), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def load_latest_data_quality_report(path: Path = DATA_QUALITY_LATEST_JSON) -> DataQualityReport | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw = payload.get("report", payload)
    if not isinstance(raw, dict):
        return None
    return data_quality_report_from_dict(raw)


def data_quality_report_from_dict(raw: dict[str, Any]) -> DataQualityReport:
    return DataQualityReport(
        generated_at=str(raw.get("generated_at", "")),
        symbols=[str(item) for item in raw.get("symbols", [])] if isinstance(raw.get("symbols"), list) else [],
        symbol_count=parse_int(raw.get("symbol_count")),
        usable_market_tape_count=parse_int(raw.get("usable_market_tape_count")),
        missing_market_tape_count=parse_int(raw.get("missing_market_tape_count")),
        provider_summary=raw.get("provider_summary", {}) if isinstance(raw.get("provider_summary"), dict) else {},
        symbol_rows=[
            DataQualitySymbol(
                symbol=str(item.get("symbol", "")),
                usable_market_tape=bool(item.get("usable_market_tape", False)),
                best_provider=str(item.get("best_provider", "")),
                providers_attempted=[str(value) for value in item.get("providers_attempted", [])]
                if isinstance(item.get("providers_attempted"), list)
                else [],
                fields_returned=[str(value) for value in item.get("fields_returned", [])]
                if isinstance(item.get("fields_returned"), list)
                else [],
                missing_fields=[str(value) for value in item.get("missing_fields", [])]
                if isinstance(item.get("missing_fields"), list)
                else [],
                provider_errors=[str(value) for value in item.get("provider_errors", [])]
                if isinstance(item.get("provider_errors"), list)
                else [],
                last_price=parse_optional_float(item.get("last_price")),
                bid=parse_optional_float(item.get("bid")),
                ask=parse_optional_float(item.get("ask")),
                spread_percent=parse_optional_float(item.get("spread_percent")),
                relative_volume=parse_optional_float(item.get("relative_volume")),
                warnings=[str(value) for value in item.get("warnings", [])]
                if isinstance(item.get("warnings"), list)
                else [],
            )
            for item in raw.get("symbol_rows", [])
            if isinstance(item, dict)
        ],
        field_summary=raw.get("field_summary", {}) if isinstance(raw.get("field_summary"), dict) else {},
        timestamp_summary=raw.get("timestamp_summary", {}) if isinstance(raw.get("timestamp_summary"), dict) else {},
        scanner_field_reliability=raw.get("scanner_field_reliability", {})
        if isinstance(raw.get("scanner_field_reliability"), dict)
        else {},
        capture_summary=raw.get("capture_summary", {}) if isinstance(raw.get("capture_summary"), dict) else {},
        minute_bar_coverage=raw.get("minute_bar_coverage", {}) if isinstance(raw.get("minute_bar_coverage"), dict) else {},
        duplicate_capture_anomalies=raw.get("duplicate_capture_anomalies", [])
        if isinstance(raw.get("duplicate_capture_anomalies"), list)
        else [],
        repeated_ticker_anomalies=raw.get("repeated_ticker_anomalies", [])
        if isinstance(raw.get("repeated_ticker_anomalies"), list)
        else [],
        warnings=[str(item) for item in raw.get("warnings", [])] if isinstance(raw.get("warnings"), list) else [],
    )


def format_data_quality_markdown(report: DataQualityReport) -> str:
    lines = [
        f"# Momentum Hunter Data Quality - {report.generated_at}",
        "",
        "Read-only diagnostic report. This does not change scoring, readiness, alerts, trade planning, or raw captures.",
        "",
        "## Summary",
        "",
        f"- Symbols checked: {report.symbol_count}",
        f"- Usable market tape: {report.usable_market_tape_count}",
        f"- Missing market tape: {report.missing_market_tape_count}",
        f"- Capture files scanned: {report.capture_summary.get('capture_file_count', 0)}",
        f"- Capture candidate rows scanned: {report.capture_summary.get('candidate_row_count', 0)}",
        f"- Duplicate ticker anomalies: {len(report.duplicate_capture_anomalies)}",
        f"- Repeated identical candidate anomalies: {len(report.repeated_ticker_anomalies)}",
        f"- Known quote timestamps: {report.timestamp_summary.get('known_timestamp_count', 0)}",
        f"- Unknown quote timestamps: {report.timestamp_summary.get('unknown_timestamp_count', 0)}",
        f"- Stale quote timestamps: {report.timestamp_summary.get('stale_timestamp_count', 0)}",
        f"- Warnings: {'; '.join(report.warnings) if report.warnings else 'none'}",
        "",
        "## Market Tape By Symbol",
        "",
        "| Symbol | Usable | Provider | Price | Bid | Ask | Spread % | Rel Vol | Missing Fields | Warnings |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report.symbol_rows:
        lines.append(
            f"| {row.symbol} | {'yes' if row.usable_market_tape else 'no'} | {row.best_provider or 'n/a'} | "
            f"{fmt(row.last_price)} | {fmt(row.bid)} | {fmt(row.ask)} | {fmt(row.spread_percent)} | "
            f"{fmt(row.relative_volume)} | {', '.join(row.missing_fields) or 'none'} | "
            f"{', '.join(row.warnings) or 'none'} |"
        )
    lines.extend(["", "## Scanner Field Reliability", ""])
    lines.extend(["| Field | Present | Missing | Zero | Total Rows |", "| --- | ---: | ---: | ---: | ---: |"])
    for field_name, row in sorted(report.scanner_field_reliability.items()):
        lines.append(
            f"| {field_name} | {row.get('present', 0)} | {row.get('missing', 0)} | "
            f"{row.get('zero', 0)} | {row.get('total_rows', 0)} |"
        )
    lines.extend(["", "## Provider Summary", ""])
    lines.extend(["| Provider | Attempts | Successes | Usable | Failures |", "| --- | ---: | ---: | ---: | ---: |"])
    for provider, row in sorted(report.provider_summary.items()):
        lines.append(
            f"| {provider} | {row.get('attempts', 0)} | {row.get('successes', 0)} | "
            f"{row.get('usable_for_alerting', 0)} | {row.get('failures', 0)} |"
        )
    lines.extend(["", "## Timestamp Quality", ""])
    lines.append(str(report.timestamp_summary.get("note", "Timestamp quality was not evaluated.")))
    lines.append("")
    lines.append(f"- Known timestamps: {report.timestamp_summary.get('known_timestamp_count', 0)}")
    lines.append(f"- Unknown timestamps: {report.timestamp_summary.get('unknown_timestamp_count', 0)}")
    lines.append(f"- Stale timestamps: {report.timestamp_summary.get('stale_timestamp_count', 0)}")
    lines.append(f"- Invalid timestamps: {report.timestamp_summary.get('invalid_timestamp_count', 0)}")
    lines.extend(["", "## Minute Bar Coverage", ""])
    lines.append(f"- Source: `{report.minute_bar_coverage.get('source_path', '')}`")
    lines.append(f"- Symbols with bars: {report.minute_bar_coverage.get('symbols_with_bars', 0)}")
    lines.append(f"- Symbols missing bars: {report.minute_bar_coverage.get('symbols_missing_bars', 0)}")
    if report.repeated_ticker_anomalies:
        lines.extend(["", "## Repeated Identical Candidate Rows", ""])
        for item in report.repeated_ticker_anomalies[:10]:
            lines.append(
                f"- {item.get('ticker')}: {item.get('repeat_count')} repeats "
                f"(price={item.get('price')}, volume={item.get('volume')}, score={item.get('score')})"
            )
    return "\n".join(lines) + "\n"


def normalize_symbols(symbols: list[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        value = normalize_symbol(symbol)
        if not value or value in seen:
            continue
        seen.add(value)
        clean.append(value)
    return clean


def normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def impossible_tape_value(field_name: str, value: object) -> bool:
    number = parse_optional_float(value)
    if number is None:
        return False
    if field_name in {"last_price", "bid", "ask"}:
        return number <= 0
    if field_name in {"spread_percent", "premarket_volume", "intraday_volume", "rvol_numerator", "rvol_denominator"}:
        return number < 0
    return False


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def parse_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_optional_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value: object) -> str:
    number = parse_optional_float(value)
    if number is None:
        return "n/a"
    return f"{number:.2f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter data-quality latest reports.")
    parser.add_argument("symbols", nargs="*", help="Optional symbols to check. Defaults to monitor targets/latest capture.")
    parser.add_argument("--max-symbols", type=int, default=5, help="Maximum default symbols to check when no symbols are supplied.")
    parser.add_argument("--json", type=Path, default=DATA_QUALITY_LATEST_JSON)
    parser.add_argument("--md", type=Path, default=DATA_QUALITY_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = args.symbols or default_symbols(max(1, args.max_symbols))
    report = build_data_quality_report(symbols)
    paths = export_data_quality_report(report, json_path=args.json, markdown_path=args.md)
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
