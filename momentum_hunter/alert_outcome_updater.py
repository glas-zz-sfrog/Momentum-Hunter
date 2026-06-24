from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import requests

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OUTCOME_WINDOWS_MINUTES,
    AlertOutcome,
    OpportunityAlert,
    classify_alert_outcome,
    is_completed_alert,
    is_unscorable_alert,
    load_alerts,
    parse_datetime,
    save_alerts,
    unscorable_outcome,
)
from momentum_hunter.outcomes import build_http_session
from momentum_hunter.time_utils import now_central


OPPORTUNITY_MINUTE_BARS_PATH = DATA_DIR / "opportunity-minute-bars.json"
ALERT_OUTCOME_UPDATE_STATUS_PATH = DATA_DIR / "alert-outcome-update-status.json"
OUTCOME_UPDATER_VERSION = "alert_outcome_minute_bar_updater_v1"


@dataclass(frozen=True)
class MinutePriceBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    source: str = "minute_bar"


@dataclass(frozen=True)
class AlertOutcomeUpdateReport:
    generated_at: str
    alert_count: int
    updated_alert_count: int
    completed_alert_count: int
    pending_alert_count: int
    unscorable_alert_count: int
    symbols_processed: list[str]
    bars_loaded_count: int
    bars_saved_path: str
    alerts_path: str
    warnings: list[str] = field(default_factory=list)


def update_alert_store_from_minute_bars(
    *,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    bars_by_symbol: dict[str, list[MinutePriceBar]] | None = None,
    fetch_missing_bars: bool = False,
    session: requests.Session | None = None,
    generated_at: datetime | None = None,
    recalculate_completed: bool = False,
    status_path: Path | None = None,
) -> AlertOutcomeUpdateReport:
    generated_at = generated_at or now_central()
    alerts = load_alerts(alerts_path)
    warnings: list[str] = []
    stored_bars = load_minute_bars(minute_bars_path)
    merged_bars = merge_minute_bars(stored_bars, bars_by_symbol or {})

    if fetch_missing_bars:
        http = session or build_http_session()
        for symbol, window in alert_fetch_windows(alerts).items():
            if symbol_has_window(merged_bars.get(symbol, []), window[0], window[1]):
                continue
            fetched = fetch_yahoo_minute_bars(http, symbol, window[0], window[1])
            if not fetched:
                warnings.append(f"NO_MINUTE_BARS_FETCHED:{symbol}")
            merged_bars = merge_minute_bars(merged_bars, {symbol: fetched})

    save_minute_bars(merged_bars, minute_bars_path)
    updated_alerts: list[OpportunityAlert] = []
    updated_count = 0
    for alert in alerts:
        if (is_completed_alert(alert) or is_unscorable_alert(alert)) and not recalculate_completed:
            updated_alerts.append(alert)
            continue
        outcome = calculate_alert_outcome_from_minute_bars(alert, merged_bars.get(alert.symbol, []))
        if outcome != alert.outcome:
            updated_count += 1
        updated_alerts.append(replace(alert, outcome=outcome))

    save_alerts(updated_alerts, alerts_path)
    completed = [alert for alert in updated_alerts if is_completed_alert(alert)]
    unscorable = [alert for alert in updated_alerts if is_unscorable_alert(alert)]
    pending = [
        alert
        for alert in updated_alerts
        if not is_completed_alert(alert) and not is_unscorable_alert(alert)
    ]
    symbols_processed = sorted({alert.symbol for alert in alerts})
    if alerts and not any(merged_bars.get(symbol) for symbol in symbols_processed):
        warnings.append("NO_MINUTE_BARS_AVAILABLE_FOR_ALERTS")
    report = AlertOutcomeUpdateReport(
        generated_at=generated_at.isoformat(),
        alert_count=len(alerts),
        updated_alert_count=updated_count,
        completed_alert_count=len(completed),
        pending_alert_count=len(pending),
        unscorable_alert_count=len(unscorable),
        symbols_processed=symbols_processed,
        bars_loaded_count=sum(len(items) for items in merged_bars.values()),
        bars_saved_path=str(minute_bars_path),
        alerts_path=str(alerts_path),
        warnings=dedupe(warnings),
    )
    if status_path is not None:
        save_update_report(report, status_path)
    return report


def save_update_report(report: AlertOutcomeUpdateReport, path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "engine_version": OUTCOME_UPDATER_VERSION,
        "report": asdict(report),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_update_report(path: Path = ALERT_OUTCOME_UPDATE_STATUS_PATH) -> AlertOutcomeUpdateReport | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    report = payload.get("report", payload)
    if not isinstance(report, dict):
        return None
    return AlertOutcomeUpdateReport(
        generated_at=str(report.get("generated_at", "")),
        alert_count=parse_optional_int(report.get("alert_count")) or 0,
        updated_alert_count=parse_optional_int(report.get("updated_alert_count")) or 0,
        completed_alert_count=parse_optional_int(report.get("completed_alert_count")) or 0,
        pending_alert_count=parse_optional_int(report.get("pending_alert_count")) or 0,
        unscorable_alert_count=parse_optional_int(report.get("unscorable_alert_count")) or 0,
        symbols_processed=[str(item) for item in report.get("symbols_processed", [])]
        if isinstance(report.get("symbols_processed"), list)
        else [],
        bars_loaded_count=parse_optional_int(report.get("bars_loaded_count")) or 0,
        bars_saved_path=str(report.get("bars_saved_path", "")),
        alerts_path=str(report.get("alerts_path", "")),
        warnings=[str(item) for item in report.get("warnings", [])] if isinstance(report.get("warnings"), list) else [],
    )


def calculate_alert_outcome_from_minute_bars(alert: OpportunityAlert, bars: list[MinutePriceBar]) -> AlertOutcome:
    if alert.price is None or alert.price <= 0:
        return unscorable_outcome("UNSCORABLE_MISSING_ENTRY_PRICE", "Missing alert price.")
    alert_time = parse_datetime(alert.timestamp)
    if alert_time is None:
        return unscorable_outcome("UNSCORABLE_INVALID_TIMESTAMP", "Invalid alert timestamp.")
    future = sorted(
        [
            bar
            for bar in bars
            if (parsed := parse_datetime(bar.timestamp)) is not None and parsed >= alert_time
        ],
        key=lambda bar: bar.timestamp,
    )
    if not future:
        return AlertOutcome(status="PENDING_OUTCOME", classification="PENDING", evaluation_notes=["No post-alert minute bars yet."])

    returns = {minutes: bar_return_at_minutes(alert, future, minutes) for minutes in OUTCOME_WINDOWS_MINUTES}
    mfe_15, mae_15 = bar_excursion(alert, future, 15)
    mfe_30, mae_30 = bar_excursion(alert, future, 30)
    mfe_60, mae_60 = bar_excursion(alert, future, 60)
    target_1_hit, target_1_time = bar_threshold_hit(alert, future, alert.target_1, direction="above")
    target_2_hit, _target_2_time = bar_threshold_hit(alert, future, alert.target_2, direction="above")
    stop_hit, stop_time = bar_threshold_hit(alert, future, alert.stop, direction="below")
    stop_before_target = stop_hit and (
        not target_1_hit or (stop_time is not None and target_1_time is not None and stop_time <= target_1_time)
    )
    latest_time = max((parse_datetime(bar.timestamp) for bar in future if parse_datetime(bar.timestamp) is not None), default=None)
    complete = latest_time is not None and (latest_time - alert_time).total_seconds() >= 60 * 60
    notes = ["Minute-bar outcome updater v1."]
    if not complete:
        notes.append("Waiting for 60-minute minute-bar window.")
    classification = classify_alert_outcome(
        alert,
        complete=complete,
        target_1_hit=target_1_hit,
        stop_before_target=stop_before_target,
        sixty_minute_return=returns[60],
        mfe_30=mfe_30,
        mae_30=mae_30,
        mfe_60=mfe_60,
        mae_60=mae_60,
    )
    return AlertOutcome(
        status="COMPLETED" if complete else "PENDING_OUTCOME",
        five_minute_return_pct=returns[5],
        fifteen_minute_return_pct=returns[15],
        thirty_minute_return_pct=returns[30],
        sixty_minute_return_pct=returns[60],
        mfe_15m_pct=mfe_15,
        mae_15m_pct=mae_15,
        mfe_30m_pct=mfe_30,
        mae_30m_pct=mae_30,
        mfe_60m_pct=mfe_60,
        mae_60m_pct=mae_60,
        target_1_hit=target_1_hit,
        target_2_hit=target_2_hit,
        stop_hit=stop_hit,
        stop_hit_before_target=stop_before_target,
        classification=classification,
        evaluation_notes=notes,
    )


def bar_return_at_minutes(alert: OpportunityAlert, bars: list[MinutePriceBar], minutes: int) -> float | None:
    target_time = add_minutes(alert.timestamp, minutes)
    if target_time is None or alert.price is None or alert.price <= 0:
        return None
    bar = first_bar_at_or_after(bars, target_time)
    if bar is None:
        return None
    return round((bar.close - alert.price) / alert.price * 100, 2)


def bar_excursion(alert: OpportunityAlert, bars: list[MinutePriceBar], minutes: int) -> tuple[float | None, float | None]:
    alert_time = parse_datetime(alert.timestamp)
    end_time = add_minutes(alert.timestamp, minutes)
    if alert_time is None or end_time is None or alert.price is None or alert.price <= 0:
        return None, None
    window = [
        bar
        for bar in bars
        if (parsed := parse_datetime(bar.timestamp)) is not None and alert_time <= parsed <= end_time
    ]
    if not window:
        return None, None
    mfe = (max(bar.high for bar in window) - alert.price) / alert.price * 100
    mae = (min(bar.low for bar in window) - alert.price) / alert.price * 100
    return round(mfe, 2), round(mae, 2)


def bar_threshold_hit(
    alert: OpportunityAlert,
    bars: list[MinutePriceBar],
    threshold: float | None,
    *,
    direction: str,
) -> tuple[bool | None, datetime | None]:
    if threshold is None:
        return None, None
    alert_time = parse_datetime(alert.timestamp)
    if alert_time is None:
        return None, None
    for bar in sorted(bars, key=lambda item: item.timestamp):
        observed_at = parse_datetime(bar.timestamp)
        if observed_at is None or observed_at < alert_time:
            continue
        if direction == "above" and bar.high >= threshold:
            return True, observed_at
        if direction == "below" and bar.low <= threshold:
            return True, observed_at
    return False, None


def first_bar_at_or_after(bars: list[MinutePriceBar], target_time: datetime) -> MinutePriceBar | None:
    for bar in sorted(bars, key=lambda item: item.timestamp):
        observed_at = parse_datetime(bar.timestamp)
        if observed_at is not None and observed_at >= target_time:
            return bar
    return None


def load_minute_bars(path: Path = OPPORTUNITY_MINUTE_BARS_PATH) -> dict[str, list[MinutePriceBar]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    raw_bars = payload.get("bars", payload)
    result: dict[str, list[MinutePriceBar]] = {}
    if not isinstance(raw_bars, dict):
        return result
    for symbol, items in raw_bars.items():
        if not isinstance(items, list):
            continue
        parsed = [minute_bar_from_dict(item, fallback_symbol=str(symbol)) for item in items if isinstance(item, dict)]
        parsed = [bar for bar in parsed if bar is not None]
        if parsed:
            result[str(symbol).upper()] = sorted(parsed, key=lambda bar: bar.timestamp)
    return result


def save_minute_bars(bars_by_symbol: dict[str, list[MinutePriceBar]], path: Path = OPPORTUNITY_MINUTE_BARS_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "engine_version": OUTCOME_UPDATER_VERSION,
        "updated_at": now_central().isoformat(),
        "bars": {
            symbol: [asdict(bar) for bar in sorted(items, key=lambda item: item.timestamp)]
            for symbol, items in sorted(normalize_bars_by_symbol(bars_by_symbol).items())
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def merge_minute_bars(
    existing: dict[str, list[MinutePriceBar]],
    new_items: dict[str, list[MinutePriceBar]],
) -> dict[str, list[MinutePriceBar]]:
    merged = normalize_bars_by_symbol(existing)
    for symbol, bars in normalize_bars_by_symbol(new_items).items():
        by_key = {(bar.timestamp, bar.source): bar for bar in merged.get(symbol, [])}
        for bar in bars:
            by_key[(bar.timestamp, bar.source)] = bar
        merged[symbol] = sorted(by_key.values(), key=lambda item: item.timestamp)
    return merged


def fetch_yahoo_minute_bars(
    session: requests.Session,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[MinutePriceBar]:
    if not symbol:
        return []
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('.', '-')}"
        f"?period1={int(start.timestamp())}&period2={int(end.timestamp())}"
        "&interval=1m&includePrePost=true&events=history"
    )
    try:
        response = session.get(url, timeout=20)
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return []
    timestamps = result[0].get("timestamp") or []
    quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    bars: list[MinutePriceBar] = []
    for index, timestamp in enumerate(timestamps):
        try:
            raw_open = quote.get("open", [])[index]
            raw_high = quote.get("high", [])[index]
            raw_low = quote.get("low", [])[index]
            raw_close = quote.get("close", [])[index]
            volumes = quote.get("volume") or []
            raw_volume = volumes[index] if index < len(volumes) else None
        except IndexError:
            continue
        if None in (raw_open, raw_high, raw_low, raw_close):
            continue
        observed_at = datetime.fromtimestamp(int(timestamp), tz=start.tzinfo)
        bars.append(
            MinutePriceBar(
                symbol=symbol.upper(),
                timestamp=observed_at.isoformat(),
                open=float(raw_open),
                high=float(raw_high),
                low=float(raw_low),
                close=float(raw_close),
                volume=int(raw_volume) if raw_volume is not None else None,
                source="yahoo_chart_1m",
            )
        )
    return bars


def alert_fetch_windows(alerts: list[OpportunityAlert]) -> dict[str, tuple[datetime, datetime]]:
    windows: dict[str, tuple[datetime, datetime]] = {}
    for alert in alerts:
        if is_completed_alert(alert) or is_unscorable_alert(alert):
            continue
        started = parse_datetime(alert.timestamp)
        if started is None:
            continue
        ended = started + timedelta(minutes=65)
        current = windows.get(alert.symbol)
        if current is None:
            windows[alert.symbol] = (started, ended)
        else:
            windows[alert.symbol] = (min(current[0], started), max(current[1], ended))
    return windows


def symbol_has_window(bars: list[MinutePriceBar], start: datetime, end: datetime) -> bool:
    if not bars:
        return False
    parsed = [parse_datetime(bar.timestamp) for bar in bars]
    parsed = [item for item in parsed if item is not None]
    return bool(parsed and min(parsed) <= start and max(parsed) >= end)


def normalize_bars_by_symbol(bars_by_symbol: dict[str, list[MinutePriceBar]]) -> dict[str, list[MinutePriceBar]]:
    normalized: dict[str, list[MinutePriceBar]] = {}
    for symbol, bars in bars_by_symbol.items():
        clean_symbol = str(symbol).strip().upper()
        if not clean_symbol:
            continue
        normalized[clean_symbol] = sorted(
            [replace(bar, symbol=clean_symbol) for bar in bars],
            key=lambda item: item.timestamp,
        )
    return normalized


def minute_bar_from_dict(payload: dict, *, fallback_symbol: str = "") -> MinutePriceBar | None:
    symbol = str(payload.get("symbol") or fallback_symbol).strip().upper()
    timestamp = str(payload.get("timestamp") or "")
    if not symbol or not timestamp:
        return None
    try:
        return MinutePriceBar(
            symbol=symbol,
            timestamp=timestamp,
            open=float(payload.get("open")),
            high=float(payload.get("high")),
            low=float(payload.get("low")),
            close=float(payload.get("close")),
            volume=parse_optional_int(payload.get("volume")),
            source=str(payload.get("source") or "minute_bar"),
        )
    except (TypeError, ValueError):
        return None


def add_minutes(timestamp: str, minutes: int) -> datetime | None:
    start = parse_datetime(timestamp)
    if start is None:
        return None
    return start + timedelta(minutes=minutes)


def parse_optional_int(value: object) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(value)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update Momentum Hunter alert outcomes from minute bars.")
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--minute-bars", type=Path, default=OPPORTUNITY_MINUTE_BARS_PATH)
    parser.add_argument("--status-path", type=Path, default=ALERT_OUTCOME_UPDATE_STATUS_PATH)
    parser.add_argument("--input-bars-json", type=Path, default=None, help="Optional JSON file containing bars keyed by symbol.")
    parser.add_argument("--fetch-missing-bars", action="store_true", help="Fetch missing 1-minute Yahoo chart bars for pending alerts.")
    args = parser.parse_args(argv)

    supplied_bars = load_minute_bars(args.input_bars_json) if args.input_bars_json else {}
    report = update_alert_store_from_minute_bars(
        alerts_path=args.alerts_path,
        minute_bars_path=args.minute_bars,
        bars_by_symbol=supplied_bars,
        fetch_missing_bars=args.fetch_missing_bars,
        status_path=args.status_path,
    )
    print(json.dumps(asdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
