"""Deterministic rolling market and sector context from canonical candle evidence.

The engine is deliberately offline and provider-neutral. It accepts already
validated bars, derives context under an explicit policy, and can preserve an
append-only snapshot chain. It does not fetch data, score candidates, build
TradePlans, evaluate risk, or contact a broker.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping, Sequence


REGIME_SCHEMA_VERSION = 1
REGIME_PROFILE = "rolling-market-sector-regime-v1"

RISK_ON = "RISK_ON"
RISK_OFF = "RISK_OFF"
MIXED = "MIXED"
SECTOR_ROTATION = "SECTOR_ROTATION"
VOLATILITY_SHOCK = "VOLATILITY_SHOCK"
EVENT_RISK = "EVENT_RISK"
DATA_STALE = "DATA_STALE"
REGIME_LABELS = frozenset(
    {
        RISK_ON,
        RISK_OFF,
        MIXED,
        SECTOR_ROTATION,
        VOLATILITY_SHOCK,
        EVENT_RISK,
        DATA_STALE,
    }
)

SUFFICIENT = "SUFFICIENT"
PARTIAL = "PARTIAL"
INSUFFICIENT = "INSUFFICIENT"
STALE = "STALE"
SUFFICIENCY_STATES = frozenset({SUFFICIENT, PARTIAL, INSUFFICIENT, STALE})

HIGH = "HIGH"
MEDIUM = "MEDIUM"
NONE = "NONE"
CONFIDENCE_STATES = frozenset({HIGH, MEDIUM, NONE})

POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"
NEUTRAL = "NEUTRAL"
UNAVAILABLE = "UNAVAILABLE"
DIRECTION_STATES = frozenset({POSITIVE, NEGATIVE, NEUTRAL, UNAVAILABLE})

NO_SCORE_AUTHORITY = "NONE"
REGIME_CHANGED = "MARKET_REGIME_CHANGED"
NO_REEVALUATION = "NO_REEVALUATION"
CANONICAL_BAR_STATES = frozenset(
    {"RECONCILED", "CORRECTED", "HISTORY_ONLY_GAP_FILL"}
)

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class RollingMarketRegimeError(ValueError):
    """Raised when regime evidence is incomplete, contradictory, or unsafe."""


@dataclass(frozen=True)
class RegimeBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_identity: str
    source_state: str = "CANONICAL"


@dataclass(frozen=True)
class RegimePolicy:
    policy_version: str
    market_symbols: tuple[str, ...]
    short_window_bars: int
    long_window_bars: int
    volatility_baseline_bars: int
    directional_return_threshold_pct: float
    alignment_fraction: float
    volatility_shock_multiple: float
    sector_rotation_dispersion_pct: float
    stale_after_seconds: int
    maximum_cross_symbol_skew_seconds: int
    maximum_internal_gap_seconds: int
    minimum_sector_symbols: int
    maximum_candidate_fan_out: int

    @property
    def fingerprint(self) -> str:
        return fingerprint_payload(asdict(self))


@dataclass(frozen=True)
class EventRiskContext:
    active: bool = False
    context_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RegimeMetric:
    symbol: str
    role: str
    bar_count: int
    first_bar_timestamp: str
    latest_bar_timestamp: str
    source_identity: str
    latest_close: float
    short_sma: float
    long_sma: float
    short_return_pct: float
    long_return_pct: float
    volatility_multiple: float
    direction: str


@dataclass(frozen=True)
class RegimeSnapshot:
    sequence: int
    snapshot_id: str
    evaluated_at: str
    regime: str
    input_sufficiency: str
    confidence: str
    transition_reason: str
    previous_snapshot_id: str
    previous_regime: str
    benchmark_symbols: tuple[str, ...]
    sector_symbols: tuple[str, ...]
    latest_bar_timestamp: str
    source_identities: tuple[str, ...]
    input_bar_identities: tuple[str, ...]
    input_fingerprint: str
    policy: RegimePolicy
    policy_version: str
    policy_fingerprint: str
    event_risk_active: bool
    event_risk_context_id: str
    event_risk_reason: str
    metrics: tuple[RegimeMetric, ...]
    score_authority: str = NO_SCORE_AUTHORITY
    trade_recommendation: bool = False
    schema_version: int = REGIME_SCHEMA_VERSION
    profile: str = REGIME_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RegimeLedger:
    snapshots: tuple[RegimeSnapshot, ...] = field(default_factory=tuple)
    schema_version: int = REGIME_SCHEMA_VERSION
    profile: str = REGIME_PROFILE


@dataclass(frozen=True)
class CandidateRegimeTarget:
    opportunity_id: str
    symbol: str
    sector_symbol: str = ""


@dataclass(frozen=True)
class CandidateRegimeContext:
    opportunity_id: str
    symbol: str
    snapshot_id: str
    market_regime: str
    sector_symbol: str
    sector_direction: str
    sector_context_available: bool
    reevaluation_status: str
    score_authority: str
    context_fingerprint: str


class RegimeSnapshotStore:
    """Atomic append-only store for deterministic regime snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> RegimeLedger:
        with self._lock:
            if not self.path.exists():
                return RegimeLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RollingMarketRegimeError(
                    f"Regime evidence cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def append(self, snapshot: RegimeSnapshot) -> RegimeSnapshot:
        with self._lock:
            ledger = self.load()
            existing = next(
                (
                    item
                    for item in ledger.snapshots
                    if item.snapshot_id == snapshot.snapshot_id
                ),
                None,
            )
            if existing is not None:
                if existing != snapshot:
                    raise RollingMarketRegimeError(
                        "Regime snapshot identity was reused with conflicting evidence."
                    )
                return existing
            expected_sequence = len(ledger.snapshots) + 1
            if snapshot.sequence != expected_sequence:
                raise RollingMarketRegimeError(
                    "Regime snapshot sequence was not append-only."
                )
            previous = ledger.snapshots[-1] if ledger.snapshots else None
            expected_previous = previous.snapshot_id if previous else ""
            if snapshot.previous_snapshot_id != expected_previous:
                raise RollingMarketRegimeError(
                    "Regime snapshot did not extend the current evidence chain."
                )
            if previous and _parse_timestamp(
                snapshot.evaluated_at, "Snapshot evaluation timestamp"
            ) <= _parse_timestamp(
                previous.evaluated_at, "Previous snapshot evaluation timestamp"
            ):
                raise RollingMarketRegimeError(
                    "Regime snapshot chronology was not strictly increasing."
                )
            validate_snapshot(snapshot)
            updated = replace(
                ledger,
                snapshots=(*ledger.snapshots, snapshot),
            )
            validate_ledger(updated)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(updated)))
            return snapshot


def derive_regime_snapshot(
    *,
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    sector_symbols: Sequence[str],
    policy: RegimePolicy,
    evaluated_at: datetime,
    previous_snapshot: RegimeSnapshot | None = None,
    event_risk: EventRiskContext | None = None,
    sequence: int | None = None,
) -> RegimeSnapshot:
    """Derive one immutable snapshot from already-canonical completed bars."""

    validate_policy(policy)
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    context = event_risk or EventRiskContext()
    _validate_event_risk(context)
    if previous_snapshot and evaluated <= _parse_timestamp(
        previous_snapshot.evaluated_at, "Previous snapshot evaluation timestamp"
    ):
        raise RollingMarketRegimeError(
            "Regime snapshot chronology must be strictly increasing."
        )
    normalized = _normalize_inputs(bars_by_symbol, evaluated)
    sectors = _normalized_symbols(sector_symbols, "Sector symbol")
    if any(symbol in policy.market_symbols for symbol in sectors):
        raise RollingMarketRegimeError(
            "Market and sector symbol roles must remain distinct."
        )

    required_count = max(
        policy.long_window_bars + 1,
        policy.volatility_baseline_bars + 1,
    )
    market_missing = [
        symbol
        for symbol in policy.market_symbols
        if len(normalized.get(symbol, ())) < required_count
    ]
    market_series = {
        symbol: normalized[symbol][-required_count:]
        for symbol in policy.market_symbols
        if symbol in normalized and len(normalized[symbol]) >= required_count
    }
    sector_series = {
        symbol: normalized[symbol][-required_count:]
        for symbol in sectors
        if symbol in normalized and len(normalized[symbol]) >= required_count
    }

    all_selected = {**market_series, **sector_series}
    stale_reasons = _stale_reasons(all_selected, evaluated, policy)
    if market_missing:
        regime = DATA_STALE
        sufficiency = INSUFFICIENT
        confidence = NONE
        metrics: tuple[RegimeMetric, ...] = ()
        reason = "INSUFFICIENT_MARKET_BARS:" + ",".join(market_missing)
    elif stale_reasons:
        regime = DATA_STALE
        sufficiency = STALE
        confidence = NONE
        metrics = _metrics(market_series, sector_series, policy)
        reason = "STALE_OR_DISCONTINUOUS_INPUT:" + ",".join(stale_reasons)
    else:
        metrics = _metrics(market_series, sector_series, policy)
        market_metrics = tuple(
            item for item in metrics if item.role == "MARKET"
        )
        sector_metrics = tuple(
            item for item in metrics if item.role == "SECTOR"
        )
        missing_sector_count = len(sectors) - len(sector_metrics)
        sufficiency = PARTIAL if missing_sector_count else SUFFICIENT
        confidence = MEDIUM if missing_sector_count else HIGH
        regime, reason = _classify(
            market_metrics,
            sector_metrics,
            policy,
            context,
        )

    used_bars = tuple(
        bar
        for symbol in sorted(all_selected)
        for bar in all_selected[symbol]
    )
    identities = tuple(
        f"{bar.symbol}|{_iso(_parse_timestamp(bar.timestamp, 'Bar timestamp'))}"
        for bar in used_bars
    )
    input_payload = [asdict(bar) for bar in used_bars]
    input_fingerprint = fingerprint_payload(input_payload)
    previous_id = previous_snapshot.snapshot_id if previous_snapshot else ""
    previous_regime = previous_snapshot.regime if previous_snapshot else ""
    transition_reason = _transition_reason(previous_regime, regime, reason)
    next_sequence = sequence if sequence is not None else (
        previous_snapshot.sequence + 1 if previous_snapshot else 1
    )
    snapshot_payload = {
        "sequence": next_sequence,
        "evaluated_at": evaluated.isoformat(),
        "regime": regime,
        "input_sufficiency": sufficiency,
        "confidence": confidence,
        "transition_reason": transition_reason,
        "previous_snapshot_id": previous_id,
        "previous_regime": previous_regime,
        "benchmark_symbols": policy.market_symbols,
        "sector_symbols": sectors,
        "latest_bar_timestamp": max(
            (_iso(_parse_timestamp(bar.timestamp, "Bar timestamp")) for bar in used_bars),
            default="",
        ),
        "source_identities": tuple(
            sorted({bar.source_identity for bar in used_bars})
        ),
        "input_bar_identities": identities,
        "input_fingerprint": input_fingerprint,
        "policy": asdict(policy),
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "event_risk_active": context.active,
        "event_risk_context_id": context.context_id,
        "event_risk_reason": context.reason,
        "metrics": tuple(asdict(item) for item in metrics),
        "score_authority": NO_SCORE_AUTHORITY,
        "trade_recommendation": False,
        "schema_version": REGIME_SCHEMA_VERSION,
        "profile": REGIME_PROFILE,
    }
    fingerprint = fingerprint_payload(snapshot_payload)
    snapshot = RegimeSnapshot(
        snapshot_id=f"regime-{fingerprint[:24]}",
        fingerprint=fingerprint,
        metrics=metrics,
        policy=policy,
        **{
            key: value
            for key, value in snapshot_payload.items()
            if key not in {"metrics", "policy"}
        },
    )
    validate_snapshot(snapshot)
    return snapshot


def fan_out_regime_context(
    snapshot: RegimeSnapshot,
    targets: Sequence[CandidateRegimeTarget],
    *,
    policy: RegimePolicy,
) -> tuple[CandidateRegimeContext, ...]:
    """Bind one context snapshot to a bounded watched-candidate set."""

    validate_snapshot(snapshot)
    validate_policy(policy)
    if snapshot.policy_fingerprint != policy.fingerprint:
        raise RollingMarketRegimeError(
            "Candidate fan-out policy did not match the regime snapshot."
        )
    if len(targets) > policy.maximum_candidate_fan_out:
        raise RollingMarketRegimeError(
            "Regime fan-out exceeded the bounded candidate limit."
        )
    sector_metrics = {
        item.symbol: item for item in snapshot.metrics if item.role == "SECTOR"
    }
    seen: set[str] = set()
    contexts: list[CandidateRegimeContext] = []
    changed = bool(
        snapshot.previous_regime and snapshot.previous_regime != snapshot.regime
    )
    for target in targets:
        opportunity_id = _required_text(target.opportunity_id, "Opportunity ID")
        if opportunity_id in seen:
            raise RollingMarketRegimeError(
                "Regime fan-out repeated an opportunity identity."
            )
        seen.add(opportunity_id)
        symbol = _normalized_symbol(target.symbol, "Candidate symbol")
        sector_symbol = (
            _normalized_symbol(target.sector_symbol, "Candidate sector symbol")
            if target.sector_symbol
            else ""
        )
        metric = sector_metrics.get(sector_symbol)
        sector_direction = metric.direction if metric else UNAVAILABLE
        payload = {
            "opportunity_id": opportunity_id,
            "symbol": symbol,
            "snapshot_id": snapshot.snapshot_id,
            "market_regime": snapshot.regime,
            "sector_symbol": sector_symbol,
            "sector_direction": sector_direction,
            "sector_context_available": metric is not None,
            "reevaluation_status": REGIME_CHANGED if changed else NO_REEVALUATION,
            "score_authority": NO_SCORE_AUTHORITY,
        }
        contexts.append(
            CandidateRegimeContext(
                context_fingerprint=fingerprint_payload(payload),
                **payload,
            )
        )
    return tuple(contexts)


def bars_from_canonical(
    bars_by_symbol: Mapping[str, Iterable[object]],
) -> dict[str, tuple[RegimeBar, ...]]:
    """Copy canonical bar values without mutating or retaining source objects."""

    converted: dict[str, tuple[RegimeBar, ...]] = {}
    for raw_symbol, bars in bars_by_symbol.items():
        symbol = _normalized_symbol(raw_symbol, "Canonical bar symbol")
        rows: list[RegimeBar] = []
        for bar in bars:
            try:
                row = RegimeBar(
                    symbol=str(getattr(bar, "symbol")),
                    timestamp=str(getattr(bar, "timestamp")),
                    open=float(getattr(bar, "open")),
                    high=float(getattr(bar, "high")),
                    low=float(getattr(bar, "low")),
                    close=float(getattr(bar, "close")),
                    volume=float(getattr(bar, "volume")),
                    source_identity=str(getattr(bar, "source")),
                    source_state=str(getattr(bar, "state")),
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise RollingMarketRegimeError(
                    "Canonical regime adapter received an invalid bar."
                ) from exc
            if _normalized_symbol(row.symbol, "Canonical bar symbol") != symbol:
                raise RollingMarketRegimeError(
                    "Canonical regime adapter received a cross-symbol bar."
                )
            rows.append(row)
        converted[symbol] = tuple(rows)
    return converted


def _classify(
    market_metrics: Sequence[RegimeMetric],
    sector_metrics: Sequence[RegimeMetric],
    policy: RegimePolicy,
    event_risk: EventRiskContext,
) -> tuple[str, str]:
    if event_risk.active:
        return EVENT_RISK, "ACTIVE_EVENT_RISK_CONTEXT"
    peak_volatility = max(item.volatility_multiple for item in market_metrics)
    if peak_volatility >= policy.volatility_shock_multiple:
        return VOLATILITY_SHOCK, "BENCHMARK_VOLATILITY_THRESHOLD_EXCEEDED"
    positive_fraction = sum(
        item.direction == POSITIVE for item in market_metrics
    ) / len(market_metrics)
    negative_fraction = sum(
        item.direction == NEGATIVE for item in market_metrics
    ) / len(market_metrics)
    market_is_mixed = (
        positive_fraction < policy.alignment_fraction
        and negative_fraction < policy.alignment_fraction
    )
    if len(sector_metrics) >= policy.minimum_sector_symbols and market_is_mixed:
        returns = [item.long_return_pct for item in sector_metrics]
        dispersion = max(returns) - min(returns)
        directions = {item.direction for item in sector_metrics}
        if (
            dispersion >= policy.sector_rotation_dispersion_pct
            and POSITIVE in directions
            and NEGATIVE in directions
        ):
            return SECTOR_ROTATION, "DIVERGENT_SECTOR_TRENDS"
    if positive_fraction >= policy.alignment_fraction:
        return RISK_ON, "POSITIVE_BENCHMARK_ALIGNMENT"
    if negative_fraction >= policy.alignment_fraction:
        return RISK_OFF, "NEGATIVE_BENCHMARK_ALIGNMENT"
    return MIXED, "BENCHMARK_ALIGNMENT_MIXED"


def _metrics(
    market_series: Mapping[str, Sequence[RegimeBar]],
    sector_series: Mapping[str, Sequence[RegimeBar]],
    policy: RegimePolicy,
) -> tuple[RegimeMetric, ...]:
    rows = [
        _metric(symbol, bars, "MARKET", policy)
        for symbol, bars in sorted(market_series.items())
    ]
    rows.extend(
        _metric(symbol, bars, "SECTOR", policy)
        for symbol, bars in sorted(sector_series.items())
    )
    return tuple(rows)


def _metric(
    symbol: str,
    bars: Sequence[RegimeBar],
    role: str,
    policy: RegimePolicy,
) -> RegimeMetric:
    closes = [bar.close for bar in bars]
    latest = bars[-1]
    short_sma = sum(closes[-policy.short_window_bars :]) / policy.short_window_bars
    long_sma = sum(closes[-policy.long_window_bars :]) / policy.long_window_bars
    short_return = _return_pct(
        closes[-(policy.short_window_bars + 1)], latest.close
    )
    long_return = _return_pct(
        closes[-(policy.long_window_bars + 1)], latest.close
    )
    ranges = [
        ((bar.high - bar.low) / bar.close) * 100.0
        for bar in bars[-(policy.volatility_baseline_bars + 1) : -1]
    ]
    baseline = median(ranges)
    latest_range = ((latest.high - latest.low) / latest.close) * 100.0
    volatility_multiple = latest_range / baseline if baseline > 0 else 1.0
    if (
        short_return >= policy.directional_return_threshold_pct
        and latest.close >= short_sma >= long_sma
    ):
        direction = POSITIVE
    elif (
        short_return <= -policy.directional_return_threshold_pct
        and latest.close <= short_sma <= long_sma
    ):
        direction = NEGATIVE
    else:
        direction = NEUTRAL
    return RegimeMetric(
        symbol=symbol,
        role=role,
        bar_count=len(bars),
        first_bar_timestamp=_iso(_parse_timestamp(bars[0].timestamp, "Bar timestamp")),
        latest_bar_timestamp=_iso(_parse_timestamp(latest.timestamp, "Bar timestamp")),
        source_identity=latest.source_identity,
        latest_close=latest.close,
        short_sma=short_sma,
        long_sma=long_sma,
        short_return_pct=short_return,
        long_return_pct=long_return,
        volatility_multiple=volatility_multiple,
        direction=direction,
    )


def _normalize_inputs(
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    evaluated_at: datetime,
) -> dict[str, tuple[RegimeBar, ...]]:
    result: dict[str, tuple[RegimeBar, ...]] = {}
    for raw_symbol, raw_bars in bars_by_symbol.items():
        symbol = _normalized_symbol(raw_symbol, "Regime input symbol")
        if symbol in result:
            raise RollingMarketRegimeError("Regime input repeated a symbol.")
        rows: list[tuple[datetime, RegimeBar]] = []
        seen: set[str] = set()
        sources: set[str] = set()
        for bar in raw_bars:
            validate_bar(bar, expected_symbol=symbol)
            timestamp = _parse_timestamp(bar.timestamp, "Bar timestamp")
            if timestamp > evaluated_at:
                raise RollingMarketRegimeError(
                    "Regime input contained a future bar."
                )
            canonical_timestamp = _iso(timestamp)
            if canonical_timestamp in seen:
                raise RollingMarketRegimeError(
                    "Regime input repeated a bar timestamp."
                )
            seen.add(canonical_timestamp)
            sources.add(bar.source_identity)
            rows.append((timestamp, replace(bar, symbol=symbol, timestamp=canonical_timestamp)))
        if len(sources) > 1:
            raise RollingMarketRegimeError(
                "Regime input mixed source identities within one symbol."
            )
        rows.sort(key=lambda item: item[0])
        result[symbol] = tuple(item[1] for item in rows)
    return result


def _stale_reasons(
    series: Mapping[str, Sequence[RegimeBar]],
    evaluated_at: datetime,
    policy: RegimePolicy,
) -> list[str]:
    reasons: list[str] = []
    latest_times: list[tuple[str, datetime]] = []
    for symbol, bars in sorted(series.items()):
        latest = _parse_timestamp(bars[-1].timestamp, "Bar timestamp")
        latest_times.append((symbol, latest))
        age = (evaluated_at - latest).total_seconds()
        if age > policy.stale_after_seconds:
            reasons.append(f"{symbol}_STALE")
        for previous, current in zip(bars, bars[1:]):
            gap = (
                _parse_timestamp(current.timestamp, "Bar timestamp")
                - _parse_timestamp(previous.timestamp, "Bar timestamp")
            ).total_seconds()
            if gap > policy.maximum_internal_gap_seconds:
                reasons.append(f"{symbol}_GAP")
                break
    market_latest = [
        timestamp
        for symbol, timestamp in latest_times
        if symbol in policy.market_symbols
    ]
    if market_latest and (
        max(market_latest) - min(market_latest)
    ).total_seconds() > policy.maximum_cross_symbol_skew_seconds:
        reasons.append("MARKET_TIMESTAMP_SKEW")
    return reasons


def validate_policy(policy: RegimePolicy) -> None:
    if not _required_text(policy.policy_version, "Regime policy version"):
        raise RollingMarketRegimeError("Regime policy version is required.")
    symbols = _normalized_symbols(policy.market_symbols, "Market symbol")
    if symbols != policy.market_symbols or len(symbols) < 1:
        raise RollingMarketRegimeError(
            "Regime policy market symbols must be normalized and nonempty."
        )
    if not 1 <= policy.short_window_bars < policy.long_window_bars:
        raise RollingMarketRegimeError(
            "Regime short window must be positive and smaller than the long window."
        )
    if policy.volatility_baseline_bars < 2:
        raise RollingMarketRegimeError(
            "Regime volatility baseline requires at least two bars."
        )
    _positive_finite(
        policy.directional_return_threshold_pct,
        "Directional return threshold",
    )
    if not 0.5 <= policy.alignment_fraction <= 1.0:
        raise RollingMarketRegimeError(
            "Regime alignment fraction must be between 0.5 and 1.0."
        )
    if policy.volatility_shock_multiple <= 1.0:
        raise RollingMarketRegimeError(
            "Volatility shock multiple must be greater than one."
        )
    _positive_finite(
        policy.sector_rotation_dispersion_pct,
        "Sector rotation dispersion",
    )
    for value, name in (
        (policy.stale_after_seconds, "Stale threshold"),
        (policy.maximum_cross_symbol_skew_seconds, "Cross-symbol skew"),
        (policy.maximum_internal_gap_seconds, "Internal gap"),
        (policy.minimum_sector_symbols, "Minimum sector symbols"),
        (policy.maximum_candidate_fan_out, "Maximum candidate fan-out"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RollingMarketRegimeError(f"{name} must be a positive integer.")


def validate_bar(bar: RegimeBar, *, expected_symbol: str) -> None:
    if _normalized_symbol(bar.symbol, "Regime bar symbol") != expected_symbol:
        raise RollingMarketRegimeError("Regime input contained a cross-symbol bar.")
    _parse_timestamp(bar.timestamp, "Bar timestamp")
    _required_text(bar.source_identity, "Bar source identity")
    if bar.source_state not in CANONICAL_BAR_STATES:
        raise RollingMarketRegimeError(
            "Regime input requires a terminal canonical bar state."
        )
    values = {
        name: _finite(getattr(bar, name), f"Bar {name}")
        for name in ("open", "high", "low", "close", "volume")
    }
    if min(values[name] for name in ("open", "high", "low", "close")) <= 0:
        raise RollingMarketRegimeError("Regime bar OHLC values must be positive.")
    if values["volume"] < 0:
        raise RollingMarketRegimeError("Regime bar volume must be nonnegative.")
    if values["high"] < max(values["open"], values["low"], values["close"]):
        raise RollingMarketRegimeError("Regime bar high was invalid.")
    if values["low"] > min(values["open"], values["high"], values["close"]):
        raise RollingMarketRegimeError("Regime bar low was invalid.")


def validate_snapshot(snapshot: RegimeSnapshot) -> None:
    if snapshot.regime not in REGIME_LABELS:
        raise RollingMarketRegimeError("Regime snapshot label was unsupported.")
    if snapshot.input_sufficiency not in SUFFICIENCY_STATES:
        raise RollingMarketRegimeError("Regime snapshot sufficiency was unsupported.")
    if snapshot.confidence not in CONFIDENCE_STATES:
        raise RollingMarketRegimeError("Regime snapshot confidence was unsupported.")
    if snapshot.score_authority != NO_SCORE_AUTHORITY:
        raise RollingMarketRegimeError("Regime snapshot claimed scoring authority.")
    if snapshot.trade_recommendation:
        raise RollingMarketRegimeError("Regime snapshot claimed a trade recommendation.")
    if snapshot.schema_version != REGIME_SCHEMA_VERSION or snapshot.profile != REGIME_PROFILE:
        raise RollingMarketRegimeError("Regime snapshot schema identity was unsupported.")
    if not _SHA256.fullmatch(snapshot.fingerprint):
        raise RollingMarketRegimeError("Regime snapshot fingerprint was invalid.")
    payload = snapshot_fingerprint_payload(snapshot)
    if fingerprint_payload(payload) != snapshot.fingerprint:
        raise RollingMarketRegimeError("Regime snapshot fingerprint did not verify.")
    if snapshot.snapshot_id != f"regime-{snapshot.fingerprint[:24]}":
        raise RollingMarketRegimeError("Regime snapshot identity did not verify.")
    if snapshot.sequence <= 0:
        raise RollingMarketRegimeError("Regime snapshot sequence was invalid.")
    _parse_timestamp(snapshot.evaluated_at, "Snapshot evaluation timestamp")
    if not _SHA256.fullmatch(snapshot.input_fingerprint):
        raise RollingMarketRegimeError("Regime input fingerprint was invalid.")
    if not _SHA256.fullmatch(snapshot.policy_fingerprint):
        raise RollingMarketRegimeError("Regime policy fingerprint was invalid.")
    validate_policy(snapshot.policy)
    if (
        snapshot.policy_version != snapshot.policy.policy_version
        or snapshot.policy_fingerprint != snapshot.policy.fingerprint
    ):
        raise RollingMarketRegimeError(
            "Regime snapshot policy identity did not verify."
        )
    if snapshot.event_risk_active and not snapshot.event_risk_context_id:
        raise RollingMarketRegimeError(
            "Active event risk lacked a context identity."
        )


def validate_ledger(ledger: RegimeLedger) -> None:
    if ledger.schema_version != REGIME_SCHEMA_VERSION or ledger.profile != REGIME_PROFILE:
        raise RollingMarketRegimeError("Regime ledger schema identity was unsupported.")
    previous: RegimeSnapshot | None = None
    seen: set[str] = set()
    for index, snapshot in enumerate(ledger.snapshots, start=1):
        validate_snapshot(snapshot)
        if snapshot.sequence != index:
            raise RollingMarketRegimeError("Regime ledger sequence was invalid.")
        if snapshot.snapshot_id in seen:
            raise RollingMarketRegimeError("Regime ledger repeated a snapshot identity.")
        seen.add(snapshot.snapshot_id)
        expected_previous = previous.snapshot_id if previous else ""
        if snapshot.previous_snapshot_id != expected_previous:
            raise RollingMarketRegimeError("Regime ledger chain was invalid.")
        if previous and _parse_timestamp(
            snapshot.evaluated_at, "Snapshot evaluation timestamp"
        ) <= _parse_timestamp(
            previous.evaluated_at, "Previous snapshot evaluation timestamp"
        ):
            raise RollingMarketRegimeError(
                "Regime ledger chronology was not strictly increasing."
            )
        previous = snapshot


def snapshot_fingerprint_payload(snapshot: RegimeSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    payload.pop("snapshot_id", None)
    payload.pop("fingerprint", None)
    return payload


def ledger_to_wire(ledger: RegimeLedger) -> dict[str, object]:
    return {
        "schemaVersion": ledger.schema_version,
        "profile": ledger.profile,
        "snapshots": [asdict(item) for item in ledger.snapshots],
    }


def ledger_from_wire(payload: object) -> RegimeLedger:
    if not isinstance(payload, Mapping):
        raise RollingMarketRegimeError("Regime ledger root was invalid.")
    if set(payload) != {"schemaVersion", "profile", "snapshots"}:
        raise RollingMarketRegimeError("Regime ledger fields were unsupported.")
    rows = payload.get("snapshots")
    if not isinstance(rows, list):
        raise RollingMarketRegimeError("Regime ledger snapshots were invalid.")
    snapshots: list[RegimeSnapshot] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise RollingMarketRegimeError("Regime ledger snapshot row was invalid.")
        body = dict(row)
        metrics = body.get("metrics")
        if not isinstance(metrics, list):
            raise RollingMarketRegimeError("Regime snapshot metrics were invalid.")
        try:
            body["metrics"] = tuple(RegimeMetric(**dict(item)) for item in metrics)
            body["policy"] = RegimePolicy(**dict(body["policy"]))
            body["policy"] = replace(
                body["policy"],
                market_symbols=tuple(body["policy"].market_symbols),
            )
            for key in (
                "benchmark_symbols",
                "sector_symbols",
                "source_identities",
                "input_bar_identities",
            ):
                body[key] = tuple(body[key])
            snapshots.append(RegimeSnapshot(**body))
        except (KeyError, TypeError, ValueError) as exc:
            raise RollingMarketRegimeError(
                "Regime snapshot fields were invalid."
            ) from exc
    try:
        return RegimeLedger(
            snapshots=tuple(snapshots),
            schema_version=int(payload["schemaVersion"]),
            profile=str(payload["profile"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RollingMarketRegimeError("Regime ledger identity was invalid.") from exc


def fingerprint_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _transition_reason(previous: str, current: str, reason: str) -> str:
    prefix = f"{previous}_TO_{current}" if previous else f"INITIAL_{current}"
    if previous == current:
        prefix = f"UNCHANGED_{current}"
    return f"{prefix}:{reason}"


def _validate_event_risk(context: EventRiskContext) -> None:
    if context.active and not _required_text(context.context_id, "Event-risk context ID"):
        raise RollingMarketRegimeError("Active event risk requires a context identity.")
    if not context.active and (context.context_id or context.reason):
        raise RollingMarketRegimeError(
            "Inactive event risk cannot carry active-context evidence."
        )


def _normalized_symbols(values: Iterable[str], name: str) -> tuple[str, ...]:
    normalized = tuple(_normalized_symbol(value, name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise RollingMarketRegimeError(f"{name} list contained duplicates.")
    return normalized


def _normalized_symbol(value: str, name: str) -> str:
    symbol = str(value or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise RollingMarketRegimeError(f"{name} was invalid.")
    return symbol


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RollingMarketRegimeError(f"{name} is required.")
    return text


def _parse_timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RollingMarketRegimeError(f"{name} was invalid.") from exc
    return _aware(parsed, name)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RollingMarketRegimeError(f"{name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RollingMarketRegimeError(f"{name} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise RollingMarketRegimeError(f"{name} must be finite.")
    return number


def _positive_finite(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise RollingMarketRegimeError(f"{name} must be positive.")
    return number


def _return_pct(start: float, end: float) -> float:
    return ((end / start) - 1.0) * 100.0
