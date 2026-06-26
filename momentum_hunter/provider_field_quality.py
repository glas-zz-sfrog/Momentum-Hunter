from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import SQLITE_DB_PATH
from momentum_hunter.storage import ANALYSIS_CSV
from momentum_hunter.time_utils import now_central


REPORTS_DIR = DATA_DIR / "reports"
ENGINE_VERSION = "provider_field_quality_v1"

FIELD_SPECS: dict[str, dict[str, Any]] = {
    "price": {"columns": ["price"], "required": True, "positive": True},
    "percent_change": {"columns": ["percent_change", "% change", "change"], "required": True, "max_abs": 1000},
    "volume": {"columns": ["volume"], "required": True, "positive": True, "zero_warning": True},
    "relative_volume": {"columns": ["relative_volume", "rel_vol", "rel vol"], "required": True, "positive": True, "zero_warning": True},
    "average_volume": {"columns": ["average_volume", "avg_volume", "avg vol"], "required": False, "positive": True, "zero_warning": True},
    "market_cap": {"columns": ["market_cap", "market cap"], "required": True, "positive": True},
    "bid": {"columns": ["bid", "current_bid"], "required": False, "positive": True},
    "ask": {"columns": ["ask", "current_ask"], "required": False, "positive": True},
    "spread": {"columns": ["spread", "spread_percent"], "required": False, "min": 0, "max": 100},
    "premarket_price": {"columns": ["premarket_price"], "required": False, "positive": True},
    "premarket_volume": {"columns": ["premarket_volume"], "required": False, "positive": True, "zero_warning": True},
    "headline_timestamp": {"columns": ["published_at", "headline_timestamp", "news_timestamp"], "required": False},
}


def build_provider_field_quality_report(
    *,
    analysis_captures_path: Path = ANALYSIS_CSV,
    db_path: Path = SQLITE_DB_PATH,
    generated_at: datetime | None = None,
    stale_after_days: int = 7,
) -> dict[str, Any]:
    generated_at = generated_at or now_central()
    rows = read_csv_rows(analysis_captures_path)
    audit_rows: list[dict[str, Any]] = []
    report_warnings: list[str] = []
    stale_row_count = 0
    for index, row in enumerate(rows, start=1):
        provider = text_value(row, "provider") or "unknown"
        scanner = text_value(row, "scanner") or "unknown"
        symbol = (text_value(row, "ticker") or text_value(row, "symbol") or "").upper()
        capture_time = text_value(row, "capture_time")
        stale = timestamp_is_stale(capture_time, generated_at=generated_at, stale_after_days=stale_after_days)
        if stale:
            stale_row_count += 1
        for field_name, spec in FIELD_SPECS.items():
            audit_rows.append(
                audit_field(
                    row,
                    row_index=index,
                    provider=provider,
                    scanner=scanner,
                    symbol=symbol,
                    capture_time=capture_time,
                    field_name=field_name,
                    spec=spec,
                    stale=stale,
                    source_path=analysis_captures_path,
                )
            )

    summaries = summarize_audit_rows(audit_rows)
    sqlite_status = sqlite_field_quality_write_status(db_path)
    if stale_row_count:
        report_warnings.append(f"STALE_CAPTURE_ROWS:{stale_row_count}")
    if rows and any(item["status"] != "PASS" for item in audit_rows):
        report_warnings.append("PROVIDER_FIELD_WARNINGS_PRESENT")
    if not rows:
        report_warnings.append(f"ANALYSIS_CAPTURE_SOURCE_EMPTY_OR_MISSING:{analysis_captures_path}")
    if sqlite_status["status"].startswith("SKIPPED"):
        report_warnings.append(sqlite_status["status"])

    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at.isoformat(),
        "overall_status": "WARN" if report_warnings else "PASS",
        "source_path": str(analysis_captures_path),
        "source_rows": len(rows),
        "audit_row_count": len(audit_rows),
        "stale_after_days": stale_after_days,
        "field_summaries": summaries["field_summaries"],
        "provider_summaries": summaries["provider_summaries"],
        "symbol_summaries": summaries["symbol_summaries"],
        "top_warnings": summaries["top_warnings"],
        "sample_audit_rows": audit_rows[:250],
        "sqlite_write_status": sqlite_status,
        "warnings": dedupe(report_warnings)[:250],
    }


def audit_field(
    row: dict[str, str],
    *,
    row_index: int,
    provider: str,
    scanner: str,
    symbol: str,
    capture_time: str,
    field_name: str,
    spec: dict[str, Any],
    stale: bool,
    source_path: Path,
) -> dict[str, Any]:
    raw_value = first_present(row, spec["columns"])
    present = raw_value not in (None, "")
    parsed = parse_numeric(raw_value)
    warnings: list[str] = []
    if not present:
        warnings.append(f"MISSING_{field_name.upper()}")
    elif parsed is not None:
        if spec.get("positive") and parsed < 0:
            warnings.append(f"IMPOSSIBLE_NEGATIVE_{field_name.upper()}")
        if spec.get("positive") and parsed == 0:
            warnings.append(f"ZERO_{field_name.upper()}")
        if spec.get("zero_warning") and parsed == 0:
            warnings.append(f"ZERO_{field_name.upper()}")
        if "min" in spec and parsed < float(spec["min"]):
            warnings.append(f"IMPOSSIBLE_LOW_{field_name.upper()}")
        if "max" in spec and parsed > float(spec["max"]):
            warnings.append(f"IMPOSSIBLE_HIGH_{field_name.upper()}")
        if "max_abs" in spec and abs(parsed) > float(spec["max_abs"]):
            warnings.append(f"IMPOSSIBLE_EXTREME_{field_name.upper()}")
    elif present and field_name != "headline_timestamp":
        warnings.append(f"UNPARSEABLE_{field_name.upper()}")
    if stale:
        warnings.append("STALE_CAPTURE_TIMESTAMP")

    if not spec.get("required") and not present:
        usability = "optional_missing"
        confidence = "unknown"
        status = "WARN" if stale else "PASS"
        warnings = [item for item in warnings if item != f"MISSING_{field_name.upper()}"]
    elif warnings:
        usability = "not_usable" if any(item.startswith(("MISSING", "IMPOSSIBLE", "UNPARSEABLE")) for item in warnings) else "usable_with_warning"
        confidence = "low" if usability == "not_usable" else "medium"
        status = "FAIL" if any(item.startswith("IMPOSSIBLE") for item in warnings) else "WARN"
    else:
        usability = "usable"
        confidence = "high"
        status = "PASS"

    return {
        "row_index": row_index,
        "provider": provider,
        "scanner": scanner,
        "symbol": symbol,
        "field_name": field_name,
        "raw_value": raw_value if raw_value is not None else "",
        "parsed_value": parsed,
        "value_present": present,
        "value_missing": not present,
        "value_zero": parsed == 0 if parsed is not None else False,
        "value_impossible": any(item.startswith("IMPOSSIBLE") for item in warnings),
        "value_stale": stale,
        "source_endpoint": str(source_path),
        "timestamp": capture_time,
        "confidence": confidence,
        "usability": usability,
        "fallback_source": "",
        "status": status,
        "warnings": dedupe(warnings),
    }


def summarize_audit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    field_counts: dict[str, Counter[str]] = defaultdict(Counter)
    provider_counts: dict[str, Counter[str]] = defaultdict(Counter)
    symbol_counts: dict[str, Counter[str]] = defaultdict(Counter)
    warning_counts: Counter[str] = Counter()
    for row in rows:
        field_counts[row["field_name"]][row["status"]] += 1
        provider_counts[row["provider"]][row["status"]] += 1
        symbol_counts[row["symbol"] or "UNKNOWN"][row["status"]] += 1
        for warning in row.get("warnings", []):
            warning_counts[str(warning)] += 1
    return {
        "field_summaries": [summary_row(name, counts) for name, counts in sorted(field_counts.items())],
        "provider_summaries": [summary_row(name, counts) for name, counts in sorted(provider_counts.items())],
        "symbol_summaries": [summary_row(name, counts) for name, counts in sorted(symbol_counts.items())],
        "top_warnings": [{"warning": warning, "count": count} for warning, count in warning_counts.most_common(25)],
    }


def summary_row(name: str, counts: Counter[str]) -> dict[str, Any]:
    total = sum(counts.values())
    warn = counts.get("WARN", 0)
    fail = counts.get("FAIL", 0)
    return {
        "name": name,
        "total": total,
        "pass": counts.get("PASS", 0),
        "warn": warn,
        "fail": fail,
        "warning_rate_pct": round((warn + fail) / total * 100, 2) if total else 0.0,
    }


def sqlite_field_quality_write_status(db_path: Path) -> dict[str, Any]:
    # Existing provider_quality_checks is symbol-level market-tape quality. It has no field_name/status columns,
    # so writing field-level audit rows into it would blur two different concepts.
    return {
        "database_path": str(db_path),
        "status": "SKIPPED_UNSUPPORTED_SCHEMA",
        "reason": "provider_quality_checks stores symbol-level market-tape checks, not field-level scanner audit rows.",
    }


def write_provider_field_quality_report(payload: dict[str, Any], *, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "provider-field-quality-latest.json"
    markdown_path = output_dir / "provider-field-quality-latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(provider_field_quality_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def provider_field_quality_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Provider Field Quality Audit",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Source: `{payload.get('source_path', '')}`",
        f"- Source rows: {payload.get('source_rows', 0)}",
        f"- Audit rows: {payload.get('audit_row_count', 0)}",
        f"- SQLite write status: {payload.get('sqlite_write_status', {}).get('status', 'UNKNOWN')}",
        "",
        "## Field Summary",
        "",
        "| Field | Total | Pass | Warn | Fail | Warning Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in payload.get("field_summaries", []):
        lines.append(
            f"| `{item['name']}` | {item['total']} | {item['pass']} | {item['warn']} | {item['fail']} | {item['warning_rate_pct']}% |"
        )
    lines.extend(["", "## Top Warnings", ""])
    warnings = payload.get("top_warnings") or []
    lines.extend([f"- {item['warning']}: {item['count']}" for item in warnings] if warnings else ["- None"])
    lines.extend(["", "## Report Warnings", ""])
    report_warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in report_warnings] if report_warnings else ["- None"])
    return "\n".join(lines) + "\n"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as file:
        return [dict(row) for row in csv.DictReader(file)]


def first_present(row: dict[str, str], keys: list[str]) -> str | None:
    normalized = {key.lower().strip(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key.lower())
        if value not in (None, ""):
            return str(value)
    return None


def text_value(row: dict[str, str], key: str) -> str:
    for row_key, value in row.items():
        if row_key.lower().strip() == key.lower():
            return str(value or "").strip()
    return ""


def parse_numeric(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text.lower() in {"n/a", "na", "none", "null", "-"}:
        return None
    multiplier = 1.0
    suffix = text[-1:].upper()
    if suffix in {"K", "M", "B", "T"}:
        text = text[:-1]
        multiplier = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0, "T": 1_000_000_000_000.0}[suffix]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def timestamp_is_stale(value: str, *, generated_at: datetime, stale_after_days: int) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None and generated_at.tzinfo is not None:
        parsed = parsed.replace(tzinfo=generated_at.tzinfo)
    return parsed < generated_at - timedelta(days=stale_after_days)


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit scanner/provider field quality from stored Momentum Hunter data.")
    parser.add_argument("--analysis-captures", type=Path, default=ANALYSIS_CSV)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--stale-after-days", type=int, default=7)
    args = parser.parse_args(argv)

    payload = build_provider_field_quality_report(
        analysis_captures_path=args.analysis_captures,
        stale_after_days=args.stale_after_days,
    )
    json_path, markdown_path = write_provider_field_quality_report(payload, output_dir=args.output_dir)
    summary = {
        "schema_version": payload.get("schema_version"),
        "engine_version": payload.get("engine_version"),
        "generated_at": payload.get("generated_at"),
        "overall_status": payload.get("overall_status"),
        "source_rows": payload.get("source_rows", 0),
        "audit_row_count": payload.get("audit_row_count", 0),
        "top_warnings": payload.get("top_warnings", [])[:10],
        "warnings": payload.get("warnings", []),
        "sqlite_write_status": payload.get("sqlite_write_status", {}),
        "report_paths": {"json": str(json_path), "markdown": str(markdown_path)},
    }
    print(json.dumps(summary, indent=2))
    return 1 if payload.get("overall_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
