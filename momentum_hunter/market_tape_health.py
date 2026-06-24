from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.outcomes import build_http_session
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    MarketTape,
    fetch_market_tape,
    fetch_nasdaq_market_tape,
    fetch_yahoo_chart_tape,
    fetch_yahoo_market_tape,
)


REPORT_SCHEMA_VERSION = 1
HEALTH_ENGINE_VERSION = "market_tape_health_v1"
REPORT_COLUMNS = [
    "Generated At",
    "Symbol",
    "Provider",
    "Status",
    "Success",
    "Usable For Alerting",
    "Source",
    "Fields Returned",
    "Error Message",
    "Last Price",
    "Premarket Price",
    "Premarket Volume",
    "Intraday Volume",
    "Bid",
    "Ask",
    "Spread %",
    "Relative Volume",
    "RVOL Numerator",
    "RVOL Denominator",
]


@dataclass(frozen=True)
class MarketTapeHealthAttempt:
    generated_at: str
    symbol: str
    provider: str
    status: str
    success: bool
    usable_for_alerting: bool
    source: str
    fields_returned: list[str] = field(default_factory=list)
    error_message: str = ""
    warnings: list[str] = field(default_factory=list)
    last_price: float | None = None
    premarket_price: float | None = None
    premarket_volume: int | None = None
    intraday_volume: int | None = None
    bid: float | None = None
    ask: float | None = None
    spread_percent: float | None = None
    relative_volume: float | None = None
    rvol_numerator: int | None = None
    rvol_denominator: int | None = None


@dataclass(frozen=True)
class MarketTapeHealthReport:
    generated_at: str
    symbols: list[str]
    attempts: list[MarketTapeHealthAttempt]
    usable_symbol_count: int
    missing_symbol_count: int
    provider_summary: dict[str, dict[str, int]]
    warnings: list[str] = field(default_factory=list)


def build_market_tape_health_report(
    symbols: list[str],
    *,
    session: requests.Session | None = None,
    generated_at: datetime | None = None,
) -> MarketTapeHealthReport:
    generated_at = generated_at or now_central()
    http = session or build_http_session()
    clean_symbols = normalize_symbols(symbols)
    attempts: list[MarketTapeHealthAttempt] = []
    for symbol in clean_symbols:
        for provider, fetcher in provider_fetchers():
            attempts.append(health_attempt(symbol, provider, fetcher(http, symbol), generated_at=generated_at))

    usable_symbols = {
        attempt.symbol
        for attempt in attempts
        if attempt.provider == "combined" and attempt.usable_for_alerting
    }
    missing_symbols = sorted(set(clean_symbols) - usable_symbols)
    warnings: list[str] = []
    if missing_symbols:
        warnings.append("SYMBOLS_WITHOUT_USABLE_MARKET_TAPE")
    if not clean_symbols:
        warnings.append("NO_SYMBOLS_REQUESTED")

    return MarketTapeHealthReport(
        generated_at=generated_at.isoformat(),
        symbols=clean_symbols,
        attempts=attempts,
        usable_symbol_count=len(usable_symbols),
        missing_symbol_count=len(missing_symbols),
        provider_summary=provider_summary(attempts),
        warnings=warnings,
    )


def provider_fetchers():
    return [
        ("combined", fetch_market_tape),
        ("nasdaq", fetch_nasdaq_market_tape),
        ("yahoo_quote_plus_chart", fetch_yahoo_market_tape),
        ("yahoo_chart_only", fetch_yahoo_chart_tape),
    ]


def health_attempt(
    symbol: str,
    provider: str,
    tape: MarketTape,
    *,
    generated_at: datetime,
) -> MarketTapeHealthAttempt:
    fields = tape_fields(tape)
    returned = [key for key, value in fields.items() if value is not None]
    usable = usable_for_alerting(tape)
    success = bool(returned)
    status = provider_status(tape, usable=usable, fields_returned=returned)
    return MarketTapeHealthAttempt(
        generated_at=generated_at.isoformat(),
        symbol=symbol,
        provider=provider,
        status=status,
        success=success,
        usable_for_alerting=usable,
        source=tape.source,
        fields_returned=returned,
        error_message="; ".join(tape.warnings),
        warnings=list(tape.warnings),
        last_price=tape.last_price,
        premarket_price=tape.premarket_price,
        premarket_volume=tape.premarket_volume,
        intraday_volume=tape.intraday_volume,
        bid=tape.current_bid,
        ask=tape.current_ask,
        spread_percent=tape.spread_percent,
        relative_volume=tape.relative_volume,
        rvol_numerator=tape.rvol_numerator,
        rvol_denominator=tape.rvol_denominator,
    )


def tape_fields(tape: MarketTape) -> dict[str, object]:
    return {
        "last_price": tape.last_price,
        "premarket_price": tape.premarket_price,
        "premarket_volume": tape.premarket_volume,
        "intraday_volume": tape.intraday_volume,
        "bid": tape.current_bid,
        "ask": tape.current_ask,
        "spread_percent": tape.spread_percent,
        "relative_volume": tape.relative_volume,
        "rvol_numerator": tape.rvol_numerator,
        "rvol_denominator": tape.rvol_denominator,
    }


def usable_for_alerting(tape: MarketTape) -> bool:
    has_price = tape.last_price is not None or tape.premarket_price is not None
    has_volume = (
        tape.premarket_volume is not None
        or tape.intraday_volume is not None
        or tape.rvol_numerator is not None
    )
    return has_price and has_volume


def provider_status(tape: MarketTape, *, usable: bool, fields_returned: list[str]) -> str:
    if not fields_returned:
        return "FAIL"
    has_clean_core = all(
        value is not None
        for value in (
            tape.last_price or tape.premarket_price,
            tape.current_bid,
            tape.current_ask,
            tape.spread_percent,
            tape.rvol_numerator,
            tape.rvol_denominator,
        )
    )
    if usable and has_clean_core:
        return "SUCCESS"
    return "PARTIAL"


def provider_summary(attempts: list[MarketTapeHealthAttempt]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for attempt in attempts:
        row = summary.setdefault(
            attempt.provider,
            {"attempts": 0, "successes": 0, "usable_for_alerting": 0, "failures": 0},
        )
        row["attempts"] += 1
        if attempt.success:
            row["successes"] += 1
        if attempt.usable_for_alerting:
            row["usable_for_alerting"] += 1
        if attempt.status == "FAIL":
            row["failures"] += 1
    return summary


def export_market_tape_health_report(
    report: MarketTapeHealthReport,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"market-tape-health-{compact_timestamp(report.generated_at)}"
    csv_path = output_dir / f"{base}.csv"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_csv(report, csv_path)
    write_json(report, json_path)
    write_markdown(report, md_path)
    return {"csv": csv_path, "json": json_path, "report": md_path}


def write_csv(report: MarketTapeHealthReport, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for attempt in report.attempts:
            writer.writerow(row_to_csv(attempt))


def write_json(report: MarketTapeHealthReport, path: Path) -> None:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "engine_version": HEALTH_ENGINE_VERSION,
        "report": {
            "generated_at": report.generated_at,
            "symbols": report.symbols,
            "usable_symbol_count": report.usable_symbol_count,
            "missing_symbol_count": report.missing_symbol_count,
            "provider_summary": report.provider_summary,
            "warnings": report.warnings,
        },
        "attempts": [asdict(attempt) for attempt in report.attempts],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(report: MarketTapeHealthReport, path: Path) -> None:
    lines = [
        "# Momentum Hunter Market Tape Health",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Symbols checked: {len(report.symbols)}",
        f"- Symbols usable for alerting: {report.usable_symbol_count}",
        f"- Symbols missing usable tape: {report.missing_symbol_count}",
        f"- Warnings: {'; '.join(report.warnings) if report.warnings else 'none'}",
        "",
        "| Symbol | Provider | Status | Usable | Source | Fields Returned | Error Message |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for attempt in report.attempts:
        lines.append(
            f"| {attempt.symbol} | {attempt.provider} | {attempt.status} | "
            f"{'yes' if attempt.usable_for_alerting else 'no'} | {attempt.source} | "
            f"{', '.join(attempt.fields_returned) or 'none'} | {attempt.error_message or 'none'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def row_to_csv(attempt: MarketTapeHealthAttempt) -> dict[str, object]:
    return {
        "Generated At": attempt.generated_at,
        "Symbol": attempt.symbol,
        "Provider": attempt.provider,
        "Status": attempt.status,
        "Success": attempt.success,
        "Usable For Alerting": attempt.usable_for_alerting,
        "Source": attempt.source,
        "Fields Returned": " | ".join(attempt.fields_returned),
        "Error Message": attempt.error_message,
        "Last Price": optional(attempt.last_price),
        "Premarket Price": optional(attempt.premarket_price),
        "Premarket Volume": optional(attempt.premarket_volume),
        "Intraday Volume": optional(attempt.intraday_volume),
        "Bid": optional(attempt.bid),
        "Ask": optional(attempt.ask),
        "Spread %": optional(attempt.spread_percent),
        "Relative Volume": optional(attempt.relative_volume),
        "RVOL Numerator": optional(attempt.rvol_numerator),
        "RVOL Denominator": optional(attempt.rvol_denominator),
    }


def normalize_symbols(symbols: list[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        value = str(symbol).strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        clean.append(value)
    return clean


def compact_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%Y%m%dT%H%M%S%f%z")


def optional(value: object) -> object:
    return "" if value is None else value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a market-tape provider health report.")
    parser.add_argument("symbols", nargs="+", help="Symbols to check, for example CRWV SOFI HOOD")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for CSV/JSON/Markdown reports.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = build_market_tape_health_report(args.symbols)
    paths = export_market_tape_health_report(report, args.output_dir)
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
