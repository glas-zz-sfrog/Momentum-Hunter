from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from statistics import mean

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


ALERT_SCHEMA_VERSION = 1
ALERT_ENGINE_VERSION = "opportunity_alert_engine_v1"
OPPORTUNITY_ALERTS_PATH = DATA_DIR / "opportunity-alerts.json"
OPPORTUNITY_MONITOR_STATE_PATH = DATA_DIR / "opportunity-monitor-state.json"
OPPORTUNITY_OBSERVATIONS_PATH = DATA_DIR / "opportunity-price-observations.json"
RVOL_THRESHOLDS = (0.5, 1.0, 1.2, 2.0)
ACTIVE_ALERT_STATES = {"PENDING_OUTCOME", "ACTIVE"}
OUTCOME_WINDOWS_MINUTES = (5, 15, 30, 60)
COMPLETED_CLASSIFICATIONS = {"SUCCESSFUL", "FAILED", "NOISE", "LATE"}
PENDING_CLASSIFICATIONS = {"PENDING"}
UNSCORABLE_OUTCOME_STATUS = "UNSCORABLE_OUTCOME"
UNSCORABLE_CLASSIFICATIONS = {
    "UNSCORABLE_MISSING_ENTRY_PRICE",
    "UNSCORABLE_MISSING_MARKET_DATA",
    "UNSCORABLE_INCOMPLETE_EVIDENCE",
    "UNSCORABLE_INVALID_TIMESTAMP",
}


@dataclass(frozen=True)
class MonitorSnapshot:
    symbol: str
    timestamp: str
    state: str
    price: float | None
    bid: float | None
    ask: float | None
    spread_percent: float | None
    volume: int | None
    premarket_volume: int | None
    premarket_percent: float | None
    rvol: float | None
    rvol_type: str
    suggested_entry: float | None
    stop: float | None
    target_1: float | None
    target_2: float | None
    previous_day_high: float | None
    support_level: float | None
    news_catalyst: str
    market_regime: str
    event_mode: bool
    source_report: str


@dataclass(frozen=True)
class PriceObservation:
    symbol: str
    timestamp: str
    price: float
    bid: float | None = None
    ask: float | None = None
    spread_percent: float | None = None
    volume: int | None = None
    rvol: float | None = None
    rvol_type: str = ""
    state: str = ""
    source_report: str = ""


@dataclass(frozen=True)
class AlertOutcome:
    status: str = "PENDING_OUTCOME"
    five_minute_return_pct: float | None = None
    fifteen_minute_return_pct: float | None = None
    thirty_minute_return_pct: float | None = None
    sixty_minute_return_pct: float | None = None
    mfe_15m_pct: float | None = None
    mae_15m_pct: float | None = None
    mfe_30m_pct: float | None = None
    mae_30m_pct: float | None = None
    mfe_60m_pct: float | None = None
    mae_60m_pct: float | None = None
    target_1_hit: bool | None = None
    target_2_hit: bool | None = None
    stop_hit: bool | None = None
    stop_hit_before_target: bool | None = None
    classification: str = "PENDING"
    evaluation_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OpportunityAlert:
    alert_id: str
    symbol: str
    timestamp: str
    alert_type: str
    current_state: str
    previous_state: str
    reason: str
    price: float | None
    bid: float | None
    ask: float | None
    spread_percent: float | None
    volume: int | None
    premarket_volume: int | None
    premarket_percent: float | None
    rvol: float | None
    rvol_type: str
    suggested_entry: float | None
    stop: float | None
    target_1: float | None
    target_2: float | None
    news_catalyst: str
    market_regime: str
    event_mode: bool
    source_report: str
    engine_version: str = ALERT_ENGINE_VERSION
    outcome: AlertOutcome = field(default_factory=AlertOutcome)


@dataclass(frozen=True)
class AlertPerformanceSummary:
    group_type: str
    group: str
    alert_count: int
    pending_count: int
    completed_count: int
    unscorable_count: int
    average_5m_return_pct: float | None
    average_15m_return_pct: float | None
    average_30m_return_pct: float | None
    average_60m_return_pct: float | None
    average_mfe_30m_pct: float | None
    average_mae_30m_pct: float | None
    win_rate_pct: float | None
    target_1_hit_rate_pct: float | None
    target_2_hit_rate_pct: float | None
    stop_hit_rate_pct: float | None


@dataclass(frozen=True)
class OpportunityAlertReport:
    generated_at: str
    source_report: str
    new_alerts: list[OpportunityAlert]
    active_alerts: list[OpportunityAlert]
    tracked_alerts: list[OpportunityAlert]
    state_transitions: list[OpportunityAlert]
    alert_type_performance: list[AlertPerformanceSummary]
    symbol_performance: list[AlertPerformanceSummary]
    readiness_state_performance: list[AlertPerformanceSummary]
    market_regime_performance: list[AlertPerformanceSummary]
    best_performing_alert_types: list[AlertPerformanceSummary]
    worst_performing_alert_types: list[AlertPerformanceSummary]
    warnings: list[str] = field(default_factory=list)


def build_opportunity_alert_report(
    trade_report_path: Path,
    *,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    state_path: Path = OPPORTUNITY_MONITOR_STATE_PATH,
    observations_path: Path = OPPORTUNITY_OBSERVATIONS_PATH,
    generated_at: datetime | None = None,
    target_symbols: set[str] | None = None,
) -> OpportunityAlertReport:
    generated_at = generated_at or now_central()
    payload = json.loads(trade_report_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {})
    current_timestamp = str(metadata.get("generated_at") or generated_at.isoformat())
    previous = load_monitor_state(state_path)
    snapshots = [
        snapshot_from_trade_candidate(item, metadata=metadata, source_report=str(trade_report_path), timestamp=current_timestamp)
        for item in payload.get("candidates", [])
        if isinstance(item, dict) and should_monitor_candidate(item, target_symbols)
    ]
    new_alerts: list[OpportunityAlert] = []
    for snapshot in snapshots:
        new_alerts.extend(detect_alerts(previous.get(snapshot.symbol), snapshot))

    observations = merge_observation_store(
        load_price_observations(observations_path),
        [observation_from_snapshot(snapshot) for snapshot in snapshots if snapshot.price is not None],
    )
    save_price_observations(observations, observations_path)
    all_alerts = update_alert_outcomes(
        merge_alert_store(load_alerts(alerts_path), new_alerts),
        observations_by_symbol(observations),
    )
    save_alerts(all_alerts, alerts_path)
    save_monitor_state({snapshot.symbol: snapshot for snapshot in snapshots}, state_path)

    active_alerts = [alert for alert in all_alerts if alert.outcome.status in ACTIVE_ALERT_STATES]
    alert_type_performance = summarize_alert_performance(all_alerts, group_type="alert_type", group_value=lambda alert: alert.alert_type)
    symbol_performance = summarize_alert_performance(all_alerts, group_type="symbol", group_value=lambda alert: alert.symbol)
    readiness_state_performance = summarize_alert_performance(all_alerts, group_type="readiness_state", group_value=lambda alert: alert.current_state)
    market_regime_performance = summarize_alert_performance(all_alerts, group_type="market_regime", group_value=lambda alert: alert.market_regime or "unknown")
    warnings = []
    if not new_alerts:
        warnings.append("No new opportunity alerts detected from latest trade-planning report.")
    if target_symbols is not None and not snapshots:
        warnings.append("No trade-planning rows matched the active monitor target universe.")
    if all(summary.completed_count == 0 for summary in alert_type_performance):
        warnings.append("No completed alert outcomes yet; leaderboard is diagnostic only.")
    return OpportunityAlertReport(
        generated_at=generated_at.isoformat(),
        source_report=str(trade_report_path),
        new_alerts=sorted(new_alerts, key=lambda alert: (alert.timestamp, alert.symbol, alert.alert_type)),
        active_alerts=sorted(active_alerts, key=lambda alert: alert.timestamp, reverse=True),
        tracked_alerts=sorted(all_alerts, key=lambda alert: alert.timestamp, reverse=True),
        state_transitions=[alert for alert in new_alerts if alert.alert_type.startswith("STATE_")],
        alert_type_performance=alert_type_performance,
        symbol_performance=symbol_performance,
        readiness_state_performance=readiness_state_performance,
        market_regime_performance=market_regime_performance,
        best_performing_alert_types=best_alert_type_summaries(alert_type_performance),
        worst_performing_alert_types=worst_alert_type_summaries(alert_type_performance),
        warnings=warnings,
    )


def should_monitor_candidate(item: dict, target_symbols: set[str] | None) -> bool:
    if target_symbols is None:
        return True
    symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
    return symbol in target_symbols


def snapshot_from_trade_candidate(item: dict, *, metadata: dict, source_report: str, timestamp: str) -> MonitorSnapshot:
    market = item.get("market_data") or {}
    tech = item.get("technical_levels") or {}
    trade_plan = item.get("trade_plan") or {}
    scoring = item.get("scoring") or {}
    price = first_float(market, "last_price", "premarket_price")
    return MonitorSnapshot(
        symbol=str(item.get("symbol", "")).upper(),
        timestamp=timestamp,
        state=str(trade_plan.get("readiness", "")),
        price=price,
        bid=parse_float(market.get("current_bid")),
        ask=parse_float(market.get("current_ask")),
        spread_percent=parse_float(market.get("spread_percent")),
        volume=parse_int(market.get("intraday_volume")),
        premarket_volume=parse_int(market.get("premarket_volume")),
        premarket_percent=parse_float(market.get("premarket_percent")),
        rvol=parse_float(market.get("relative_volume")),
        rvol_type=str(market.get("rvol_type", "")),
        suggested_entry=parse_float(trade_plan.get("bullish_entry")),
        stop=parse_float(trade_plan.get("bullish_stop")),
        target_1=parse_float(trade_plan.get("bullish_target_1")),
        target_2=parse_float(trade_plan.get("bullish_target_2")),
        previous_day_high=parse_float(tech.get("previous_day_high")),
        support_level=parse_float(tech.get("support_level")),
        news_catalyst=str(scoring.get("catalyst_summary", "")),
        market_regime=str(metadata.get("market_regime", "unknown") or "unknown"),
        event_mode=bool(metadata.get("event_mode", False)),
        source_report=source_report,
    )


def detect_alerts(previous: MonitorSnapshot | None, current: MonitorSnapshot) -> list[OpportunityAlert]:
    alerts: list[OpportunityAlert] = []
    if not current.symbol:
        return alerts
    if previous is None:
        if current.state.startswith("EXECUTION_READY"):
            alerts.append(make_alert(current, "INITIAL_EXECUTION_READY", "", "Initial observed state is execution-ready."))
        return alerts

    alerts.extend(detect_state_transition(previous, current))
    alerts.extend(detect_rvol_crosses(previous, current))
    alerts.extend(detect_breakouts(previous, current))
    alerts.extend(detect_price_expansion(previous, current))
    alerts.extend(detect_news_catalyst_change(previous, current))
    return alerts


def detect_state_transition(previous: MonitorSnapshot, current: MonitorSnapshot) -> list[OpportunityAlert]:
    if previous.state == current.state:
        return []
    alert_type = f"STATE_{normalize_token(previous.state)}_TO_{normalize_token(current.state)}"
    reason = f"Trade-planning state changed from {previous.state or 'unknown'} to {current.state or 'unknown'}."
    return [make_alert(current, alert_type, previous.state, reason)]


def detect_rvol_crosses(previous: MonitorSnapshot, current: MonitorSnapshot) -> list[OpportunityAlert]:
    if previous.rvol is None or current.rvol is None:
        return []
    alerts = []
    for threshold in RVOL_THRESHOLDS:
        if previous.rvol < threshold <= current.rvol:
            alerts.append(
                make_alert(
                    current,
                    f"RVOL_CROSS_{threshold_label(threshold)}",
                    previous.state,
                    f"RVOL crossed {threshold:g}: {previous.rvol:g} -> {current.rvol:g}.",
                )
            )
    return alerts


def detect_breakouts(previous: MonitorSnapshot, current: MonitorSnapshot) -> list[OpportunityAlert]:
    if previous.price is None or current.price is None:
        return []
    alerts = []
    if current.previous_day_high and previous.price < current.previous_day_high <= current.price:
        alerts.append(
            make_alert(
                current,
                "BREAKOUT_PREVIOUS_DAY_HIGH",
                previous.state,
                f"Price crossed previous-day high {current.previous_day_high:g}: {previous.price:g} -> {current.price:g}.",
            )
        )
    if current.suggested_entry and previous.price < current.suggested_entry <= current.price:
        alerts.append(
            make_alert(
                current,
                "BREAKOUT_PLANNED_ENTRY",
                previous.state,
                f"Price crossed planned entry {current.suggested_entry:g}: {previous.price:g} -> {current.price:g}.",
            )
        )
    if current.support_level and previous.price < current.support_level <= current.price:
        alerts.append(
            make_alert(
                current,
                "RECLAIM_SUPPORT",
                previous.state,
                f"Price reclaimed support {current.support_level:g}: {previous.price:g} -> {current.price:g}.",
            )
        )
    return alerts


def detect_price_expansion(previous: MonitorSnapshot, current: MonitorSnapshot) -> list[OpportunityAlert]:
    if previous.price is None or current.price is None or previous.price <= 0:
        return []
    minutes = minutes_between(previous.timestamp, current.timestamp)
    if minutes is None or minutes <= 0:
        return []
    move_pct = ((current.price - previous.price) / previous.price) * 100
    alerts = []
    if minutes <= 5 and move_pct >= 1.0:
        alerts.append(make_alert(current, "PRICE_EXPANSION_1PCT_5M", previous.state, f"Price moved {move_pct:.2f}% in {minutes:.1f} minutes."))
    if minutes <= 15 and move_pct >= 2.0:
        alerts.append(make_alert(current, "PRICE_EXPANSION_2PCT_15M", previous.state, f"Price moved {move_pct:.2f}% in {minutes:.1f} minutes."))
    return alerts


def detect_news_catalyst_change(previous: MonitorSnapshot, current: MonitorSnapshot) -> list[OpportunityAlert]:
    previous_text = normalize_catalyst_text(previous.news_catalyst)
    current_text = normalize_catalyst_text(current.news_catalyst)
    if not current_text or current_text == previous_text:
        return []
    if current_text.startswith("monitor coverage row"):
        return []
    if previous_text:
        reason = f"Catalyst changed from '{previous.news_catalyst}' to '{current.news_catalyst}'."
    else:
        reason = f"New catalyst appeared: {current.news_catalyst}"
    return [make_alert(current, "BREAKING_NEWS_CATALYST", previous.state, reason)]


def make_alert(snapshot: MonitorSnapshot, alert_type: str, previous_state: str, reason: str) -> OpportunityAlert:
    alert_id = stable_alert_id(snapshot.symbol, snapshot.timestamp, alert_type)
    return OpportunityAlert(
        alert_id=alert_id,
        symbol=snapshot.symbol,
        timestamp=snapshot.timestamp,
        alert_type=alert_type,
        current_state=snapshot.state,
        previous_state=previous_state,
        reason=reason,
        price=snapshot.price,
        bid=snapshot.bid,
        ask=snapshot.ask,
        spread_percent=snapshot.spread_percent,
        volume=snapshot.volume,
        premarket_volume=snapshot.premarket_volume,
        premarket_percent=snapshot.premarket_percent,
        rvol=snapshot.rvol,
        rvol_type=snapshot.rvol_type,
        suggested_entry=snapshot.suggested_entry,
        stop=snapshot.stop,
        target_1=snapshot.target_1,
        target_2=snapshot.target_2,
        news_catalyst=snapshot.news_catalyst,
        market_regime=snapshot.market_regime,
        event_mode=snapshot.event_mode,
        source_report=snapshot.source_report,
    )


def load_alerts(path: Path = OPPORTUNITY_ALERTS_PATH) -> list[OpportunityAlert]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [alert_from_dict(item) for item in payload.get("alerts", []) if isinstance(item, dict)]


def save_alerts(alerts: list[OpportunityAlert], path: Path = OPPORTUNITY_ALERTS_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ALERT_SCHEMA_VERSION,
        "engine_version": ALERT_ENGINE_VERSION,
        "updated_at": now_central().isoformat(),
        "alerts": [alert_to_dict(alert) for alert in sorted(alerts, key=lambda item: (item.timestamp, item.symbol, item.alert_type))],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def merge_alert_store(existing: list[OpportunityAlert], new_alerts: list[OpportunityAlert]) -> list[OpportunityAlert]:
    by_id = {alert.alert_id: alert for alert in existing}
    for alert in new_alerts:
        by_id.setdefault(alert.alert_id, alert)
    return list(by_id.values())


def load_monitor_state(path: Path = OPPORTUNITY_MONITOR_STATE_PATH) -> dict[str, MonitorSnapshot]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    snapshots = {}
    for item in payload.get("symbols", []):
        if isinstance(item, dict) and item.get("symbol"):
            snapshot = snapshot_from_dict(item)
            snapshots[snapshot.symbol] = snapshot
    return snapshots


def save_monitor_state(snapshots: dict[str, MonitorSnapshot], path: Path = OPPORTUNITY_MONITOR_STATE_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ALERT_SCHEMA_VERSION,
        "engine_version": ALERT_ENGINE_VERSION,
        "updated_at": now_central().isoformat(),
        "symbols": [asdict(snapshot) for snapshot in sorted(snapshots.values(), key=lambda item: item.symbol)],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def observation_from_snapshot(snapshot: MonitorSnapshot) -> PriceObservation:
    return PriceObservation(
        symbol=snapshot.symbol,
        timestamp=snapshot.timestamp,
        price=float(snapshot.price or 0),
        bid=snapshot.bid,
        ask=snapshot.ask,
        spread_percent=snapshot.spread_percent,
        volume=snapshot.volume,
        rvol=snapshot.rvol,
        rvol_type=snapshot.rvol_type,
        state=snapshot.state,
        source_report=snapshot.source_report,
    )


def load_price_observations(path: Path = OPPORTUNITY_OBSERVATIONS_PATH) -> list[PriceObservation]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        observation_from_dict(item)
        for item in payload.get("observations", [])
        if isinstance(item, dict) and item.get("symbol") and item.get("timestamp")
    ]


def save_price_observations(observations: list[PriceObservation], path: Path = OPPORTUNITY_OBSERVATIONS_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ALERT_SCHEMA_VERSION,
        "engine_version": ALERT_ENGINE_VERSION,
        "updated_at": now_central().isoformat(),
        "observations": [
            asdict(item)
            for item in sorted(observations, key=lambda obs: (obs.timestamp, obs.symbol, obs.source_report))
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def merge_observation_store(existing: list[PriceObservation], new_items: list[PriceObservation]) -> list[PriceObservation]:
    by_key = {(item.symbol, item.timestamp, item.source_report): item for item in existing}
    for item in new_items:
        by_key[(item.symbol, item.timestamp, item.source_report)] = item
    return list(by_key.values())


def observations_by_symbol(observations: list[PriceObservation]) -> dict[str, list[PriceObservation]]:
    grouped: dict[str, list[PriceObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.symbol, []).append(observation)
    return {symbol: sorted(items, key=lambda item: item.timestamp) for symbol, items in grouped.items()}


def update_alert_outcomes(
    alerts: list[OpportunityAlert],
    observations: dict[str, list[PriceObservation]],
) -> list[OpportunityAlert]:
    updated = []
    for alert in alerts:
        if is_completed_alert(alert) or is_unscorable_alert(alert):
            updated.append(alert)
            continue
        outcome = calculate_alert_outcome(alert, observations.get(alert.symbol, []))
        updated.append(replace(alert, outcome=outcome))
    return updated


def calculate_alert_outcome(alert: OpportunityAlert, observations: list[PriceObservation]) -> AlertOutcome:
    if alert.price is None or alert.price <= 0:
        return unscorable_outcome("UNSCORABLE_MISSING_ENTRY_PRICE", "Missing alert price.")
    alert_time = parse_datetime(alert.timestamp)
    if alert_time is None:
        return unscorable_outcome("UNSCORABLE_INVALID_TIMESTAMP", "Invalid alert timestamp.")
    future = [
        item
        for item in observations
        if parse_datetime(item.timestamp) is not None and parse_datetime(item.timestamp) >= alert_time
    ]
    if not future:
        return AlertOutcome(status="PENDING_OUTCOME", classification="PENDING", evaluation_notes=["No post-alert observations yet."])
    returns = {minutes: return_at_minutes(alert, future, minutes) for minutes in OUTCOME_WINDOWS_MINUTES}
    mfe_15, mae_15 = excursion(alert, future, 15)
    mfe_30, mae_30 = excursion(alert, future, 30)
    mfe_60, mae_60 = excursion(alert, future, 60)
    target_1_hit, target_1_time = threshold_hit(alert, future, alert.target_1, direction="above")
    target_2_hit, _target_2_time = threshold_hit(alert, future, alert.target_2, direction="above")
    stop_hit, stop_time = threshold_hit(alert, future, alert.stop, direction="below")
    stop_before_target = stop_hit and (not target_1_hit or (stop_time is not None and target_1_time is not None and stop_time <= target_1_time))
    latest_time = max((parse_datetime(item.timestamp) for item in future if parse_datetime(item.timestamp) is not None), default=None)
    complete = latest_time is not None and (latest_time - alert_time).total_seconds() >= 60 * 60
    notes = []
    if not complete:
        notes.append("Waiting for 60-minute observation window.")
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


def return_at_minutes(alert: OpportunityAlert, observations: list[PriceObservation], minutes: int) -> float | None:
    target_time = add_minutes(alert.timestamp, minutes)
    if target_time is None or alert.price is None or alert.price <= 0:
        return None
    observation = first_observation_at_or_after(observations, target_time)
    if observation is None:
        return None
    return round((observation.price - alert.price) / alert.price * 100, 2)


def excursion(alert: OpportunityAlert, observations: list[PriceObservation], minutes: int) -> tuple[float | None, float | None]:
    end_time = add_minutes(alert.timestamp, minutes)
    alert_time = parse_datetime(alert.timestamp)
    if end_time is None or alert_time is None or alert.price is None or alert.price <= 0:
        return None, None
    window = [
        item
        for item in observations
        if (parsed := parse_datetime(item.timestamp)) is not None and alert_time <= parsed <= end_time
    ]
    if not window:
        return None, None
    returns = [(item.price - alert.price) / alert.price * 100 for item in window]
    return round(max(returns), 2), round(min(returns), 2)


def threshold_hit(
    alert: OpportunityAlert,
    observations: list[PriceObservation],
    threshold: float | None,
    *,
    direction: str,
) -> tuple[bool | None, datetime | None]:
    if threshold is None:
        return None, None
    alert_time = parse_datetime(alert.timestamp)
    if alert_time is None:
        return None, None
    for observation in observations:
        observed_at = parse_datetime(observation.timestamp)
        if observed_at is None or observed_at < alert_time:
            continue
        if direction == "above" and observation.price >= threshold:
            return True, observed_at
        if direction == "below" and observation.price <= threshold:
            return True, observed_at
    return False, None


def classify_alert_outcome(
    alert: OpportunityAlert,
    *,
    complete: bool,
    target_1_hit: bool | None,
    stop_before_target: bool | None,
    sixty_minute_return: float | None,
    mfe_30: float | None,
    mae_30: float | None,
    mfe_60: float | None,
    mae_60: float | None,
) -> str:
    if not complete:
        return "PENDING"
    if alert.price is not None and alert.target_1 is not None and alert.price >= alert.target_1:
        return "LATE"
    if stop_before_target:
        return "FAILED"
    if target_1_hit or (mfe_30 is not None and mfe_30 >= 2.0):
        return "SUCCESSFUL"
    if mae_30 is not None and mae_30 <= -2.0 and (mfe_30 is None or mfe_30 < 1.0):
        return "FAILED"
    if sixty_minute_return is not None:
        if sixty_minute_return >= 1.0:
            return "SUCCESSFUL"
        if sixty_minute_return <= -1.0:
            return "FAILED"
    if (mfe_60 is not None and mfe_60 < 1.0) and (mae_60 is not None and mae_60 > -1.0):
        return "NOISE"
    return "NOISE"


def unscorable_outcome(classification: str, note: str) -> AlertOutcome:
    return AlertOutcome(
        status=UNSCORABLE_OUTCOME_STATUS,
        classification=classification,
        evaluation_notes=[note, "Terminal data-quality outcome; excluded from performance math and evidence thresholds."],
    )


def is_completed_alert(alert: OpportunityAlert) -> bool:
    return alert.outcome.classification in COMPLETED_CLASSIFICATIONS


def is_pending_alert(alert: OpportunityAlert) -> bool:
    return alert.outcome.classification in PENDING_CLASSIFICATIONS and alert.outcome.status in ACTIVE_ALERT_STATES


def is_unscorable_alert(alert: OpportunityAlert) -> bool:
    return alert.outcome.status == UNSCORABLE_OUTCOME_STATUS or alert.outcome.classification in UNSCORABLE_CLASSIFICATIONS


def first_observation_at_or_after(observations: list[PriceObservation], target_time: datetime) -> PriceObservation | None:
    for observation in sorted(observations, key=lambda item: item.timestamp):
        observed_at = parse_datetime(observation.timestamp)
        if observed_at is not None and observed_at >= target_time:
            return observation
    return None


def add_minutes(timestamp: str, minutes: int) -> datetime | None:
    start = parse_datetime(timestamp)
    if start is None:
        return None
    from datetime import timedelta

    return start + timedelta(minutes=minutes)


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def export_opportunity_alert_report(report: OpportunityAlertReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = safe_stamp(report.generated_at)
    base = f"opportunity-alerts-{stamp}"
    csv_path = output_dir / f"{base}.csv"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_alert_csv(report, csv_path)
    write_alert_json(report, json_path)
    write_alert_markdown(report, md_path)
    return {"csv": csv_path, "json": json_path, "report": md_path}


def write_alert_csv(report: OpportunityAlertReport, path: Path) -> None:
    columns = [
        "Alert ID",
        "Symbol",
        "Timestamp",
        "Alert Type",
        "Current State",
        "Previous State",
        "Reason",
        "Price",
        "Bid",
        "Ask",
        "Spread %",
        "Volume",
        "Premarket Volume",
        "Premarket %",
        "RVOL",
        "RVOL Type",
        "Suggested Entry",
        "Stop",
        "Target 1",
        "Target 2",
        "Outcome Status",
        "Classification",
        "5m Return %",
        "15m Return %",
        "30m Return %",
        "60m Return %",
        "MFE 30m %",
        "MAE 30m %",
        "Target 1 Hit",
        "Stop Hit",
        "Stop Before Target",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for alert in report.new_alerts:
            writer.writerow(alert_to_csv(alert))


def write_alert_json(report: OpportunityAlertReport, path: Path) -> None:
    payload = {
        "schema_version": ALERT_SCHEMA_VERSION,
        "engine_version": ALERT_ENGINE_VERSION,
        "generated_at": report.generated_at,
        "source_report": report.source_report,
        "warnings": report.warnings,
        "new_alerts": [alert_to_dict(alert) for alert in report.new_alerts],
        "active_alerts": [alert_to_dict(alert) for alert in report.active_alerts],
        "tracked_alerts": [alert_to_dict(alert) for alert in report.tracked_alerts],
        "state_transitions": [alert_to_dict(alert) for alert in report.state_transitions],
        "alert_type_performance": [asdict(item) for item in report.alert_type_performance],
        "symbol_performance": [asdict(item) for item in report.symbol_performance],
        "readiness_state_performance": [asdict(item) for item in report.readiness_state_performance],
        "market_regime_performance": [asdict(item) for item in report.market_regime_performance],
        "best_performing_alert_types": [asdict(item) for item in report.best_performing_alert_types],
        "worst_performing_alert_types": [asdict(item) for item in report.worst_performing_alert_types],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_alert_markdown(report: OpportunityAlertReport, path: Path) -> None:
    lines = [
        f"# Momentum Hunter Opportunity Alerts - {report.generated_at}",
        "",
        "Research and alert-validation output only. This does not place orders or connect to a broker.",
        "",
        f"- Source trade report: `{report.source_report}`",
        f"- Alert engine: `{ALERT_ENGINE_VERSION}`",
        "",
        "## Active Alerts",
        "",
    ]
    lines.extend(alert_table_lines(report.active_alerts[:25], empty="ACTIVE ALERTS: NONE"))
    lines.extend(["", "## New Alerts", ""])
    lines.extend(alert_table_lines(report.new_alerts, empty="NEW ALERTS: NONE"))
    lines.extend(["", "## State Transitions", ""])
    lines.extend(alert_table_lines(report.state_transitions, empty="STATE TRANSITIONS: NONE YET"))
    lines.extend(["", "## Alert Outcome Tracker", ""])
    lines.extend(outcome_tracker_lines(report.tracked_alerts[:25]))
    lines.extend(["", "## Alert Type Performance", ""])
    lines.extend(alert_performance_lines(report.alert_type_performance))
    lines.extend(["", "## Symbol Performance", ""])
    lines.extend(alert_performance_lines(report.symbol_performance))
    lines.extend(["", "## Readiness State Performance", ""])
    lines.extend(alert_performance_lines(report.readiness_state_performance))
    lines.extend(["", "## Market Regime Performance", ""])
    lines.extend(alert_performance_lines(report.market_regime_performance))
    lines.extend(["", "## Best Performing Alert Types", ""])
    lines.extend(alert_performance_lines(report.best_performing_alert_types))
    lines.extend(["", "## Worst Performing Alert Types", ""])
    lines.extend(alert_performance_lines(report.worst_performing_alert_types))
    lines.extend(["", "## Warnings", ""])
    if report.warnings:
        lines.extend([f"- {warning}" for warning in report.warnings])
    else:
        lines.append("- None.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def alert_table_lines(alerts: list[OpportunityAlert], *, empty: str) -> list[str]:
    if not alerts:
        return [f"- {empty}", ""]
    lines = [
        "| Time | Symbol | Alert Type | State | Price | RVOL | Spread | Entry | Stop | Reason | Outcome |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for alert in alerts:
        lines.append(
            f"| {alert.timestamp} | {alert.symbol} | {alert.alert_type} | {alert.current_state} | "
            f"{format_optional(alert.price)} | {format_optional(alert.rvol)} | {format_optional(alert.spread_percent)} | "
            f"{format_optional(alert.suggested_entry)} | {format_optional(alert.stop)} | {alert.reason} | {alert.outcome.classification} |"
        )
    lines.append("")
    return lines


def outcome_tracker_lines(alerts: list[OpportunityAlert]) -> list[str]:
    if not alerts:
        return ["- ALERT OUTCOME TRACKER: NO ALERTS TRACKED YET", ""]
    lines = [
        "| Time | Symbol | Alert Type | Status | Class | 5m | 15m | 30m | 60m | MFE 30m | MAE 30m | T1 | Stop |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for alert in alerts:
        outcome = alert.outcome
        lines.append(
            f"| {alert.timestamp} | {alert.symbol} | {alert.alert_type} | {outcome.status} | {outcome.classification} | "
            f"{format_optional(outcome.five_minute_return_pct)} | {format_optional(outcome.fifteen_minute_return_pct)} | "
            f"{format_optional(outcome.thirty_minute_return_pct)} | {format_optional(outcome.sixty_minute_return_pct)} | "
            f"{format_optional(outcome.mfe_30m_pct)} | {format_optional(outcome.mae_30m_pct)} | "
            f"{format_bool(outcome.target_1_hit)} | {format_bool(outcome.stop_hit)} |"
        )
    lines.append("")
    return lines


def alert_performance_lines(rows: list[AlertPerformanceSummary]) -> list[str]:
    if not rows:
        return ["- No completed alert outcomes yet.", ""]
    lines = [
        "| Group | Count | Completed | Pending | Unscorable | Win Rate | Avg 15m | Avg 60m | Avg MFE 30m | Avg MAE 30m | T1 Hit | Stop Hit |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.group} | {row.alert_count} | {row.completed_count} | {row.pending_count} | {row.unscorable_count} | "
            f"{format_optional(row.win_rate_pct)} | {format_optional(row.average_15m_return_pct)} | "
            f"{format_optional(row.average_60m_return_pct)} | {format_optional(row.average_mfe_30m_pct)} | "
            f"{format_optional(row.average_mae_30m_pct)} | {format_optional(row.target_1_hit_rate_pct)} | "
            f"{format_optional(row.stop_hit_rate_pct)} |"
        )
    lines.append("")
    return lines


def summarize_alert_performance(
    alerts: list[OpportunityAlert],
    *,
    group_type: str,
    group_value,
) -> list[AlertPerformanceSummary]:
    by_group: dict[str, list[OpportunityAlert]] = {}
    for alert in alerts:
        key = str(group_value(alert) or "unknown")
        by_group.setdefault(key, []).append(alert)
    rows = []
    for group, items in by_group.items():
        completed = [item for item in items if is_completed_alert(item)]
        unscorable = [item for item in items if is_unscorable_alert(item)]
        pending = [item for item in items if is_pending_alert(item)]
        wins = [item for item in completed if item.outcome.classification == "SUCCESSFUL"]
        target_1_hits = [item for item in completed if item.outcome.target_1_hit is True]
        target_2_hits = [item for item in completed if item.outcome.target_2_hit is True]
        stop_hits = [item for item in completed if item.outcome.stop_hit is True]
        rows.append(
            AlertPerformanceSummary(
                group_type=group_type,
                group=group,
                alert_count=len(items),
                pending_count=len(pending),
                completed_count=len(completed),
                unscorable_count=len(unscorable),
                average_5m_return_pct=average([item.outcome.five_minute_return_pct for item in completed]),
                average_15m_return_pct=average([item.outcome.fifteen_minute_return_pct for item in completed]),
                average_30m_return_pct=average([item.outcome.thirty_minute_return_pct for item in completed]),
                average_60m_return_pct=average([item.outcome.sixty_minute_return_pct for item in completed]),
                average_mfe_30m_pct=average([item.outcome.mfe_30m_pct for item in completed]),
                average_mae_30m_pct=average([item.outcome.mae_30m_pct for item in completed]),
                win_rate_pct=percent(len(wins), len(completed)),
                target_1_hit_rate_pct=percent(len(target_1_hits), len(completed)),
                target_2_hit_rate_pct=percent(len(target_2_hits), len(completed)),
                stop_hit_rate_pct=percent(len(stop_hits), len(completed)),
            )
        )
    return sorted(rows, key=lambda item: (item.completed_count, item.win_rate_pct or 0, item.group), reverse=True)


def best_alert_type_summaries(rows: list[AlertPerformanceSummary]) -> list[AlertPerformanceSummary]:
    completed = [row for row in rows if row.completed_count]
    return sorted(completed, key=lambda item: (item.win_rate_pct or 0, item.average_mfe_30m_pct or 0), reverse=True)[:10]


def worst_alert_type_summaries(rows: list[AlertPerformanceSummary]) -> list[AlertPerformanceSummary]:
    completed = [row for row in rows if row.completed_count]
    return sorted(completed, key=lambda item: (item.win_rate_pct or 0, item.average_mae_30m_pct or 0))[:10]


def alert_to_dict(alert: OpportunityAlert) -> dict:
    payload = asdict(alert)
    payload["outcome"] = asdict(alert.outcome)
    return payload


def alert_from_dict(payload: dict) -> OpportunityAlert:
    outcome_payload = payload.get("outcome") or {}
    return OpportunityAlert(
        alert_id=str(payload.get("alert_id", "")),
        symbol=str(payload.get("symbol", "")),
        timestamp=str(payload.get("timestamp", "")),
        alert_type=str(payload.get("alert_type", "")),
        current_state=str(payload.get("current_state", "")),
        previous_state=str(payload.get("previous_state", "")),
        reason=str(payload.get("reason", "")),
        price=parse_float(payload.get("price")),
        bid=parse_float(payload.get("bid")),
        ask=parse_float(payload.get("ask")),
        spread_percent=parse_float(payload.get("spread_percent")),
        volume=parse_int(payload.get("volume")),
        premarket_volume=parse_int(payload.get("premarket_volume")),
        premarket_percent=parse_float(payload.get("premarket_percent")),
        rvol=parse_float(payload.get("rvol")),
        rvol_type=str(payload.get("rvol_type", "")),
        suggested_entry=parse_float(payload.get("suggested_entry")),
        stop=parse_float(payload.get("stop")),
        target_1=parse_float(payload.get("target_1")),
        target_2=parse_float(payload.get("target_2")),
        news_catalyst=str(payload.get("news_catalyst", "")),
        market_regime=str(payload.get("market_regime", "")),
        event_mode=bool(payload.get("event_mode", False)),
        source_report=str(payload.get("source_report", "")),
        engine_version=str(payload.get("engine_version", ALERT_ENGINE_VERSION)),
        outcome=AlertOutcome(
            status=str(outcome_payload.get("status", "PENDING_OUTCOME")),
            five_minute_return_pct=parse_float(outcome_payload.get("five_minute_return_pct")),
            fifteen_minute_return_pct=parse_float(outcome_payload.get("fifteen_minute_return_pct")),
            thirty_minute_return_pct=parse_float(outcome_payload.get("thirty_minute_return_pct")),
            sixty_minute_return_pct=parse_float(outcome_payload.get("sixty_minute_return_pct")),
            mfe_15m_pct=parse_float(outcome_payload.get("mfe_15m_pct")),
            mae_15m_pct=parse_float(outcome_payload.get("mae_15m_pct")),
            mfe_30m_pct=parse_float(outcome_payload.get("mfe_30m_pct")),
            mae_30m_pct=parse_float(outcome_payload.get("mae_30m_pct")),
            mfe_60m_pct=parse_float(outcome_payload.get("mfe_60m_pct")),
            mae_60m_pct=parse_float(outcome_payload.get("mae_60m_pct")),
            target_1_hit=parse_optional_bool(outcome_payload.get("target_1_hit")),
            target_2_hit=parse_optional_bool(outcome_payload.get("target_2_hit")),
            stop_hit=parse_optional_bool(outcome_payload.get("stop_hit")),
            stop_hit_before_target=parse_optional_bool(outcome_payload.get("stop_hit_before_target")),
            classification=str(outcome_payload.get("classification", "PENDING")),
            evaluation_notes=[
                str(item)
                for item in outcome_payload.get("evaluation_notes", [])
                if str(item)
            ]
            if isinstance(outcome_payload.get("evaluation_notes"), list)
            else [],
        ),
    )


def snapshot_from_dict(payload: dict) -> MonitorSnapshot:
    return MonitorSnapshot(
        symbol=str(payload.get("symbol", "")).upper(),
        timestamp=str(payload.get("timestamp", "")),
        state=str(payload.get("state", "")),
        price=parse_float(payload.get("price")),
        bid=parse_float(payload.get("bid")),
        ask=parse_float(payload.get("ask")),
        spread_percent=parse_float(payload.get("spread_percent")),
        volume=parse_int(payload.get("volume")),
        premarket_volume=parse_int(payload.get("premarket_volume")),
        premarket_percent=parse_float(payload.get("premarket_percent")),
        rvol=parse_float(payload.get("rvol")),
        rvol_type=str(payload.get("rvol_type", "")),
        suggested_entry=parse_float(payload.get("suggested_entry")),
        stop=parse_float(payload.get("stop")),
        target_1=parse_float(payload.get("target_1")),
        target_2=parse_float(payload.get("target_2")),
        previous_day_high=parse_float(payload.get("previous_day_high")),
        support_level=parse_float(payload.get("support_level")),
        news_catalyst=str(payload.get("news_catalyst", "")),
        market_regime=str(payload.get("market_regime", "")),
        event_mode=bool(payload.get("event_mode", False)),
        source_report=str(payload.get("source_report", "")),
    )


def observation_from_dict(payload: dict) -> PriceObservation:
    return PriceObservation(
        symbol=str(payload.get("symbol", "")).upper(),
        timestamp=str(payload.get("timestamp", "")),
        price=parse_float(payload.get("price")) or 0.0,
        bid=parse_float(payload.get("bid")),
        ask=parse_float(payload.get("ask")),
        spread_percent=parse_float(payload.get("spread_percent")),
        volume=parse_int(payload.get("volume")),
        rvol=parse_float(payload.get("rvol")),
        rvol_type=str(payload.get("rvol_type", "")),
        state=str(payload.get("state", "")),
        source_report=str(payload.get("source_report", "")),
    )


def alert_to_csv(alert: OpportunityAlert) -> dict[str, object]:
    return {
        "Alert ID": alert.alert_id,
        "Symbol": alert.symbol,
        "Timestamp": alert.timestamp,
        "Alert Type": alert.alert_type,
        "Current State": alert.current_state,
        "Previous State": alert.previous_state,
        "Reason": alert.reason,
        "Price": alert.price,
        "Bid": alert.bid,
        "Ask": alert.ask,
        "Spread %": alert.spread_percent,
        "Volume": alert.volume,
        "Premarket Volume": alert.premarket_volume,
        "Premarket %": alert.premarket_percent,
        "RVOL": alert.rvol,
        "RVOL Type": alert.rvol_type,
        "Suggested Entry": alert.suggested_entry,
        "Stop": alert.stop,
        "Target 1": alert.target_1,
        "Target 2": alert.target_2,
        "Outcome Status": alert.outcome.status,
        "Classification": alert.outcome.classification,
        "5m Return %": alert.outcome.five_minute_return_pct,
        "15m Return %": alert.outcome.fifteen_minute_return_pct,
        "30m Return %": alert.outcome.thirty_minute_return_pct,
        "60m Return %": alert.outcome.sixty_minute_return_pct,
        "MFE 30m %": alert.outcome.mfe_30m_pct,
        "MAE 30m %": alert.outcome.mae_30m_pct,
        "Target 1 Hit": alert.outcome.target_1_hit,
        "Stop Hit": alert.outcome.stop_hit,
        "Stop Before Target": alert.outcome.stop_hit_before_target,
    }


def stable_alert_id(symbol: str, timestamp: str, alert_type: str) -> str:
    raw = f"{symbol}|{timestamp}|{alert_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def normalize_token(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.upper()).strip("_") or "UNKNOWN"


def normalize_catalyst_text(value: str) -> str:
    lowered = str(value or "").lower()
    cleaned = "".join(char if char.isalnum() else " " for char in lowered)
    return " ".join(cleaned.split())


def threshold_label(value: float) -> str:
    return str(value).replace(".", "_")


def minutes_between(start: str, end: str) -> float | None:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return None
    return (end_dt - start_dt).total_seconds() / 60


def first_float(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = parse_float(payload.get(key))
        if value is not None:
            return value
    return None


def parse_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_optional_bool(value: object) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return bool(value)


def average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(mean(clean), 2)


def percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def format_optional(value: float | int | None) -> str:
    return "n/a" if value is None else str(value)


def format_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def safe_stamp(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "-").replace(".", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Momentum Hunter opportunity alerts from a trade-planning report.")
    parser.add_argument("--trade-report", type=Path, required=True, help="Path to a trade-plan briefing JSON report.")
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--state-path", type=Path, default=OPPORTUNITY_MONITOR_STATE_PATH)
    parser.add_argument("--observations-path", type=Path, default=OPPORTUNITY_OBSERVATIONS_PATH)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    report = build_opportunity_alert_report(
        args.trade_report,
        alerts_path=args.alerts_path,
        state_path=args.state_path,
        observations_path=args.observations_path,
    )
    paths = export_opportunity_alert_report(report, output_dir=args.output_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
