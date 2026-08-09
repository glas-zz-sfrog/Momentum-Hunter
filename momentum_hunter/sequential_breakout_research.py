"""Append-only sequential breakout evidence for offline/prospective research.

The detector consumes already-observed completed canonical bars. It does not
fetch data, score candidates, build TradePlans, select trades, or contact a
broker. Thresholds are versioned research policy, not execution rules.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.candidate_lifecycle import (
    expected_opportunity_id,
    expected_setup_id,
    normalize_symbol,
)
from momentum_hunter.canonical_candle_evidence import (
    CANONICAL_OUTCOME_STATES,
    CanonicalMinuteBar,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
)


SEQUENTIAL_BREAKOUT_SCHEMA_VERSION = 1
SEQUENTIAL_BREAKOUT_PROFILE = "sequential-breakout-research-v1"
RESEARCH_ONLY = "RESEARCH_ONLY"
NO_EXECUTION_AUTHORITY = "NO_EXECUTION_AUTHORITY"
PROSPECTIVE = "PROSPECTIVE"
HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
OBSERVATION_MODES = frozenset({PROSPECTIVE, HISTORICAL_REPLAY})

IMPULSE_DETECTED = "IMPULSE_DETECTED"
BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
ENTRY_MISSED = "ENTRY_MISSED"
FAILED_BREAKOUT = "FAILED_BREAKOUT"
PULLBACK_FORMING = "PULLBACK_FORMING"
RECLAIM_CONFIRMED = "RECLAIM_CONFIRMED"
EXHAUSTION_RISK = "EXHAUSTION_RISK"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
EVENT_TYPES = frozenset(
    {
        IMPULSE_DETECTED,
        BREAKOUT_CONFIRMED,
        ENTRY_MISSED,
        FAILED_BREAKOUT,
        PULLBACK_FORMING,
        RECLAIM_CONFIRMED,
        EXHAUSTION_RISK,
        DATA_UNAVAILABLE,
    }
)
BREAKOUT_SETUP_FAMILIES = frozenset(
    {OPENING_BREAKOUT, CONTINUATION_BREAKOUT}
)
UNSCOPED_EVENT_TYPES = frozenset({IMPULSE_DETECTED, DATA_UNAVAILABLE})
BREAKOUT_EVENT_TYPES = frozenset(
    {BREAKOUT_CONFIRMED, ENTRY_MISSED, FAILED_BREAKOUT, EXHAUSTION_RISK}
)

EASTERN_TZ = ZoneInfo("America/New_York")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class SequentialBreakoutError(ValueError):
    """Raised when research evidence is invalid, contradictory, or tampered."""


@dataclass(frozen=True)
class SequentialBreakoutPolicy:
    policy_version: str = "sequential-breakout-policy-v1"
    prior_range_bars: int = 15
    opening_range_bars: int = 30
    range_baseline_bars: int = 20
    volume_baseline_bars: int = 20
    impulse_window_bars: int = 5
    impulse_range_multiple: float = 2.0
    volume_confirmation_multiple: float = 1.5
    missed_range_multiple: float = 0.5
    pullback_range_multiple: float = 0.25
    exhaustion_range_multiple: float = 3.0
    max_sequence_bars: int = 60
    opening_range_start: str = "09:30"
    opening_breakout_cutoff: str = "10:30"

    @property
    def fingerprint(self) -> str:
        return policy_fingerprint(self)


@dataclass(frozen=True)
class SequentialBreakoutObservation:
    symbol: str
    session_date: str
    provider_timestamp: str
    receipt_timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    source_state: str
    source_evidence_fingerprint: str
    observation_mode: str
    fingerprint: str = ""


@dataclass(frozen=True)
class SequentialBreakoutEvent:
    event_index: int
    event_id: str
    fingerprint: str
    opportunity_id: str
    originating_evidence_family: str
    symbol: str
    session_date: str
    event_type: str
    setup_id: str
    setup_family: str
    setup_sequence: int
    predecessor_setup_id: str
    provider_timestamp: str
    receipt_timestamp: str
    observation_mode: str
    source: str
    source_state: str
    source_evidence_fingerprint: str
    observed_price: float | None
    trigger_price: float | None
    prior_range_value: float | None
    distance_from_trigger_pct: float | None
    volume: float | None
    relative_volume: float | None
    reason: str
    previous_event_id: str
    policy_version: str
    policy_fingerprint: str
    authority: str = RESEARCH_ONLY
    execution_authority: bool = False
    schema_version: int = SEQUENTIAL_BREAKOUT_SCHEMA_VERSION
    profile: str = SEQUENTIAL_BREAKOUT_PROFILE


@dataclass(frozen=True)
class SequentialBreakoutLedger:
    policy: SequentialBreakoutPolicy
    events: tuple[SequentialBreakoutEvent, ...] = field(default_factory=tuple)
    schema_version: int = SEQUENTIAL_BREAKOUT_SCHEMA_VERSION
    profile: str = SEQUENTIAL_BREAKOUT_PROFILE


@dataclass
class _ActiveBreakout:
    setup_id: str
    setup_family: str
    setup_sequence: int
    trigger_price: float
    start_index: int
    predecessor_setup_id: str = ""
    missed: bool = False
    failed: bool = False
    pullback_created: bool = False
    exhausted: bool = False


class SequentialBreakoutStore:
    """Explicit-path atomic research ledger with conflict-safe idempotency."""

    def __init__(self, path: Path, *, policy: SequentialBreakoutPolicy) -> None:
        validate_policy(policy)
        self.path = path
        self.policy = policy

    def load(self) -> SequentialBreakoutLedger:
        if not self.path.exists():
            return SequentialBreakoutLedger(policy=self.policy)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SequentialBreakoutError(
                f"Sequential breakout evidence cannot be loaded: {type(exc).__name__}"
            ) from exc
        ledger = ledger_from_wire(payload)
        validate_ledger(ledger)
        if ledger.policy != self.policy:
            raise SequentialBreakoutError(
                "Sequential breakout policy conflicts with stored evidence."
            )
        return ledger

    def append(
        self, events: Iterable[SequentialBreakoutEvent]
    ) -> SequentialBreakoutLedger:
        current = self.load()
        by_id = {event.event_id: event for event in current.events}
        changed = False
        for event in events:
            validate_event(event, policy=self.policy)
            existing = by_id.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise SequentialBreakoutError(
                        "Sequential breakout event identity conflicts with stored evidence."
                    )
                continue
            by_id[event.event_id] = event
            changed = True
        combined = tuple(sorted(by_id.values(), key=event_sort_key))
        updated = replace(current, events=combined)
        validate_ledger(updated)
        if changed:
            self._save(updated)
        return updated

    def _save(self, ledger: SequentialBreakoutLedger) -> None:
        content = canonical_json_bytes(ledger_to_wire(ledger))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def observation_from_canonical_bar(
    bar: CanonicalMinuteBar,
    *,
    receipt_timestamp: datetime | str,
    observation_mode: str,
) -> SequentialBreakoutObservation:
    """Copy a canonical bar into immutable research input without mutation."""

    return build_observation(
        symbol=bar.symbol,
        session_date=bar.session_date,
        provider_timestamp=bar.timestamp,
        receipt_timestamp=receipt_timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        source_state=bar.state,
        observation_mode=observation_mode,
    )


def build_observation(
    *,
    symbol: str,
    session_date: str,
    provider_timestamp: datetime | str,
    receipt_timestamp: datetime | str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    source: str,
    source_state: str,
    observation_mode: str,
) -> SequentialBreakoutObservation:
    normalized_symbol = normalize_symbol(symbol)
    normalized_session = normalize_session_date(session_date)
    provider = aware_text(provider_timestamp, "Provider timestamp")
    receipt = aware_text(receipt_timestamp, "Receipt timestamp")
    if aware_datetime(receipt) < aware_datetime(provider):
        raise SequentialBreakoutError(
            "Sequential breakout receipt timestamp precedes provider evidence."
        )
    mode = str(observation_mode).strip().upper()
    if mode not in OBSERVATION_MODES:
        raise SequentialBreakoutError(
            "Sequential breakout observation mode is unsupported."
        )
    normalized_state = str(source_state).strip().upper()
    if normalized_state not in CANONICAL_OUTCOME_STATES:
        raise SequentialBreakoutError(
            "Sequential breakout observations require terminal canonical bars."
        )
    normalized_source = require_text(source, "Candle source")
    values = validate_ohlcv(open, high, low, close, volume)
    if (
        aware_datetime(provider).astimezone(EASTERN_TZ).date().isoformat()
        != normalized_session
    ):
        raise SequentialBreakoutError(
            "Sequential breakout bar timestamp contradicts the market session date."
        )
    source_fingerprint = stable_hash(
        "sequential-breakout-source-v1",
        normalized_symbol,
        normalized_session,
        provider,
        normalized_source,
        normalized_state,
        *(canonical_number(values[name]) for name in ("open", "high", "low", "close", "volume")),
    )
    observation = SequentialBreakoutObservation(
        symbol=normalized_symbol,
        session_date=normalized_session,
        provider_timestamp=provider,
        receipt_timestamp=receipt,
        open=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
        source=normalized_source,
        source_state=normalized_state,
        source_evidence_fingerprint=source_fingerprint,
        observation_mode=mode,
    )
    return replace(observation, fingerprint=observation_fingerprint(observation))


def detect_sequential_breakout_events(
    observations: Sequence[SequentialBreakoutObservation],
    *,
    originating_evidence_family: str,
    policy: SequentialBreakoutPolicy | None = None,
) -> tuple[SequentialBreakoutEvent, ...]:
    """Detect one symbol/session sequence using only prior and current bars."""

    policy = policy or SequentialBreakoutPolicy()
    validate_policy(policy)
    family = require_text(
        originating_evidence_family, "Originating evidence family"
    ).upper()
    if not observations:
        raise SequentialBreakoutError(
            "Sequential breakout detection requires at least one observation."
        )
    validate_observations(observations)
    symbol = observations[0].symbol
    session_date = observations[0].session_date
    opportunity_id = expected_opportunity_id(symbol, session_date, family)

    events: list[SequentialBreakoutEvent] = []
    setup_sequence = 0
    active: _ActiveBreakout | None = None
    segment_start = 0
    impulse_emitted = False
    opening_trigger = opening_range_trigger(observations, policy)

    def emit(
        *,
        observation: SequentialBreakoutObservation,
        event_type: str,
        reason: str,
        setup_id: str = "",
        setup_family: str = "",
        current_setup_sequence: int = 0,
        predecessor_setup_id: str = "",
        trigger_price: float | None = None,
        prior_range_value: float | None = None,
        relative_volume: float | None = None,
    ) -> SequentialBreakoutEvent:
        previous_event_id = events[-1].event_id if events else ""
        event = SequentialBreakoutEvent(
            event_index=len(events) + 1,
            event_id="",
            fingerprint="",
            opportunity_id=opportunity_id,
            originating_evidence_family=family,
            symbol=symbol,
            session_date=session_date,
            event_type=event_type,
            setup_id=setup_id,
            setup_family=setup_family,
            setup_sequence=current_setup_sequence,
            predecessor_setup_id=predecessor_setup_id,
            provider_timestamp=observation.provider_timestamp,
            receipt_timestamp=observation.receipt_timestamp,
            observation_mode=observation.observation_mode,
            source=observation.source,
            source_state=observation.source_state,
            source_evidence_fingerprint=observation.source_evidence_fingerprint,
            observed_price=rounded(observation.close),
            trigger_price=rounded(trigger_price),
            prior_range_value=rounded(prior_range_value),
            distance_from_trigger_pct=distance_pct(
                observation.close, trigger_price
            ),
            volume=rounded(observation.volume),
            relative_volume=rounded(relative_volume, digits=4),
            reason=require_text(reason, "Sequential breakout event reason"),
            previous_event_id=previous_event_id,
            policy_version=policy.policy_version,
            policy_fingerprint=policy.fingerprint,
        )
        event = replace(event, event_id=expected_event_id(event))
        event = replace(event, fingerprint=event_fingerprint(event))
        validate_event(event, policy=policy)
        events.append(event)
        return event

    if len(observations) < policy.prior_range_bars + 1:
        emit(
            observation=observations[-1],
            event_type=DATA_UNAVAILABLE,
            reason=(
                f"Only {len(observations)} completed bar(s) are available; "
                f"{policy.prior_range_bars + 1} are required."
            ),
        )
        return tuple(events)

    for index, current in enumerate(observations):
        if index:
            gap_seconds = int(
                (
                    aware_datetime(current.provider_timestamp)
                    - aware_datetime(observations[index - 1].provider_timestamp)
                ).total_seconds()
            )
            if gap_seconds != 60:
                emit(
                    observation=current,
                    event_type=DATA_UNAVAILABLE,
                    reason=(
                        "Canonical sequence has a noncontiguous interval: "
                        f"{gap_seconds} seconds."
                    ),
                )
                segment_start = index
                active = None
                impulse_emitted = False
                continue

        prior_range = baseline_range(
            observations, index, segment_start, policy.range_baseline_bars
        )
        relative_volume = prior_relative_volume(
            observations, index, segment_start, policy.volume_baseline_bars
        )

        if (
            not impulse_emitted
            and prior_range is not None
            and relative_volume is not None
            and relative_volume >= policy.volume_confirmation_multiple
            and index - segment_start >= policy.impulse_window_bars
        ):
            start = observations[index - policy.impulse_window_bars]
            if current.close - start.close >= prior_range * policy.impulse_range_multiple:
                emit(
                    observation=current,
                    event_type=IMPULSE_DETECTED,
                    reason=(
                        "Price velocity and relative volume exceeded the "
                        "frozen research policy."
                    ),
                    prior_range_value=prior_range,
                    relative_volume=relative_volume,
                )
                impulse_emitted = True

        if active is not None:
            age = index - active.start_index
            if age > policy.max_sequence_bars:
                active = None
            elif active.failed:
                previous = observations[index - 1] if index else current
                if previous.close <= active.trigger_price < current.close:
                    setup_sequence += 1
                    reclaim_id = expected_setup_id(
                        opportunity_id, RECLAIM, setup_sequence
                    )
                    emit(
                        observation=current,
                        event_type=RECLAIM_CONFIRMED,
                        reason="Price crossed back above the preserved failed-breakout trigger.",
                        setup_id=reclaim_id,
                        setup_family=RECLAIM,
                        current_setup_sequence=setup_sequence,
                        predecessor_setup_id=active.setup_id,
                        trigger_price=active.trigger_price,
                        prior_range_value=prior_range,
                        relative_volume=relative_volume,
                    )
                    active = None
                    continue
            else:
                if current.close < active.trigger_price:
                    emit(
                        observation=current,
                        event_type=FAILED_BREAKOUT,
                        reason="Close fell below the preserved breakout trigger.",
                        setup_id=active.setup_id,
                        setup_family=active.setup_family,
                        current_setup_sequence=active.setup_sequence,
                        predecessor_setup_id=active.predecessor_setup_id,
                        trigger_price=active.trigger_price,
                        prior_range_value=prior_range,
                        relative_volume=relative_volume,
                    )
                    active.failed = True
                else:
                    if (
                        prior_range is not None
                        and not active.pullback_created
                        and index > active.start_index
                        and current.low
                        <= active.trigger_price
                        + prior_range * policy.pullback_range_multiple
                        and current.close >= active.trigger_price
                    ):
                        setup_sequence += 1
                        pullback_id = expected_setup_id(
                            opportunity_id, PULLBACK, setup_sequence
                        )
                        emit(
                            observation=current,
                            event_type=PULLBACK_FORMING,
                            reason=(
                                "Price retested the preserved trigger without "
                                "closing below it."
                            ),
                            setup_id=pullback_id,
                            setup_family=PULLBACK,
                            current_setup_sequence=setup_sequence,
                            predecessor_setup_id=active.setup_id,
                            trigger_price=active.trigger_price,
                            prior_range_value=prior_range,
                            relative_volume=relative_volume,
                        )
                        active.pullback_created = True
                    if (
                        prior_range is not None
                        and not active.exhausted
                        and current.close - active.trigger_price
                        >= prior_range * policy.exhaustion_range_multiple
                    ):
                        emit(
                            observation=current,
                            event_type=EXHAUSTION_RISK,
                            reason=(
                                "Distance above the preserved trigger exceeded "
                                "the frozen range multiple."
                            ),
                            setup_id=active.setup_id,
                            setup_family=active.setup_family,
                            current_setup_sequence=active.setup_sequence,
                            predecessor_setup_id=active.predecessor_setup_id,
                            trigger_price=active.trigger_price,
                            prior_range_value=prior_range,
                            relative_volume=relative_volume,
                        )
                        active.exhausted = True

        if active is not None or prior_range is None or index == 0:
            continue

        trigger: float | None = None
        setup_family = ""
        eastern_time = aware_datetime(current.provider_timestamp).astimezone(
            EASTERN_TZ
        ).time()
        cutoff = parsed_clock(policy.opening_breakout_cutoff)
        if (
            segment_start == 0
            and opening_trigger is not None
            and eastern_time <= cutoff
            and observations[index - 1].close <= opening_trigger < current.close
        ):
            trigger = opening_trigger
            setup_family = OPENING_BREAKOUT
        elif index - segment_start >= policy.prior_range_bars + 1:
            prior_high = max(
                item.high
                for item in observations[index - policy.prior_range_bars : index]
            )
            previous_prior_high = max(
                item.high
                for item in observations[
                    index - policy.prior_range_bars - 1 : index - 1
                ]
            )
            if current.close > prior_high and observations[index - 1].close <= previous_prior_high:
                trigger = prior_high
                setup_family = CONTINUATION_BREAKOUT

        if trigger is None:
            continue
        setup_sequence += 1
        setup_id = expected_setup_id(opportunity_id, setup_family, setup_sequence)
        emit(
            observation=current,
            event_type=BREAKOUT_CONFIRMED,
            reason="Close crossed above a trigger computed only from prior completed bars.",
            setup_id=setup_id,
            setup_family=setup_family,
            current_setup_sequence=setup_sequence,
            trigger_price=trigger,
            prior_range_value=prior_range,
            relative_volume=relative_volume,
        )
        active = _ActiveBreakout(
            setup_id=setup_id,
            setup_family=setup_family,
            setup_sequence=setup_sequence,
            trigger_price=trigger,
            start_index=index,
        )
        if current.low > trigger + prior_range * policy.missed_range_multiple:
            emit(
                observation=current,
                event_type=ENTRY_MISSED,
                reason=(
                    "The first confirmed bar was already beyond the frozen "
                    "entry-distance policy."
                ),
                setup_id=setup_id,
                setup_family=setup_family,
                current_setup_sequence=setup_sequence,
                trigger_price=trigger,
                prior_range_value=prior_range,
                relative_volume=relative_volume,
            )
            active.missed = True
        if current.close - trigger >= prior_range * policy.exhaustion_range_multiple:
            emit(
                observation=current,
                event_type=EXHAUSTION_RISK,
                reason="The confirmation bar exceeded the frozen exhaustion range multiple.",
                setup_id=setup_id,
                setup_family=setup_family,
                current_setup_sequence=setup_sequence,
                trigger_price=trigger,
                prior_range_value=prior_range,
                relative_volume=relative_volume,
            )
            active.exhausted = True

    validate_event_sequence(events, policy=policy)
    return tuple(events)


def detect_and_store_sequential_breakouts(
    observations: Sequence[SequentialBreakoutObservation],
    *,
    originating_evidence_family: str,
    store: SequentialBreakoutStore,
) -> SequentialBreakoutLedger:
    events = detect_sequential_breakout_events(
        observations,
        originating_evidence_family=originating_evidence_family,
        policy=store.policy,
    )
    return store.append(events)


def validate_observations(
    observations: Sequence[SequentialBreakoutObservation],
) -> None:
    first = observations[0]
    prior_time: datetime | None = None
    seen: set[str] = set()
    for observation in observations:
        validate_observation(observation)
        if (
            observation.symbol != first.symbol
            or observation.session_date != first.session_date
        ):
            raise SequentialBreakoutError(
                "Sequential breakout observations crossed symbol or session identity."
            )
        current_time = aware_datetime(observation.provider_timestamp)
        if prior_time is not None and current_time <= prior_time:
            raise SequentialBreakoutError(
                "Sequential breakout observations are not strictly chronological."
            )
        if observation.provider_timestamp in seen:
            raise SequentialBreakoutError(
                "Sequential breakout observation timestamp is duplicated."
            )
        seen.add(observation.provider_timestamp)
        prior_time = current_time


def validate_observation(observation: SequentialBreakoutObservation) -> None:
    rebuilt = build_observation(
        symbol=observation.symbol,
        session_date=observation.session_date,
        provider_timestamp=observation.provider_timestamp,
        receipt_timestamp=observation.receipt_timestamp,
        open=observation.open,
        high=observation.high,
        low=observation.low,
        close=observation.close,
        volume=observation.volume,
        source=observation.source,
        source_state=observation.source_state,
        observation_mode=observation.observation_mode,
    )
    if rebuilt != observation:
        raise SequentialBreakoutError(
            "Sequential breakout observation fingerprint is invalid."
        )


def validate_ledger(ledger: SequentialBreakoutLedger) -> None:
    if ledger.schema_version != SEQUENTIAL_BREAKOUT_SCHEMA_VERSION:
        raise SequentialBreakoutError(
            "Sequential breakout ledger schema is unsupported."
        )
    if ledger.profile != SEQUENTIAL_BREAKOUT_PROFILE:
        raise SequentialBreakoutError(
            "Sequential breakout ledger profile is unsupported."
        )
    validate_policy(ledger.policy)
    seen: dict[str, SequentialBreakoutEvent] = {}
    grouped: dict[str, list[SequentialBreakoutEvent]] = {}
    for event in ledger.events:
        validate_event(event, policy=ledger.policy)
        previous = seen.get(event.event_id)
        if previous is not None:
            raise SequentialBreakoutError(
                "Sequential breakout event identity is duplicated."
            )
        seen[event.event_id] = event
        grouped.setdefault(event.opportunity_id, []).append(event)
    if tuple(sorted(ledger.events, key=event_sort_key)) != ledger.events:
        raise SequentialBreakoutError(
            "Sequential breakout ledger order is noncanonical."
        )
    for events in grouped.values():
        validate_event_sequence(events, policy=ledger.policy)


def validate_event_sequence(
    events: Sequence[SequentialBreakoutEvent],
    *,
    policy: SequentialBreakoutPolicy,
) -> None:
    previous_id = ""
    opportunity_id = events[0].opportunity_id if events else ""
    setup_ids: dict[int, str] = {}
    observed_setup_ids: set[str] = set()
    failed_setup_ids: set[str] = set()
    highest_setup_sequence = 0
    observation_mode = events[0].observation_mode if events else ""
    previous_provider_time: datetime | None = None
    for expected_index, event in enumerate(events, start=1):
        validate_event(event, policy=policy)
        if event.opportunity_id != opportunity_id:
            raise SequentialBreakoutError(
                "Sequential breakout sequence crossed opportunity identity."
            )
        if event.observation_mode != observation_mode:
            raise SequentialBreakoutError(
                "Sequential breakout sequence mixed observation modes."
            )
        provider_time = aware_datetime(event.provider_timestamp)
        if previous_provider_time is not None and provider_time < previous_provider_time:
            raise SequentialBreakoutError(
                "Sequential breakout event chronology moved backward."
            )
        if event.event_index != expected_index:
            raise SequentialBreakoutError(
                "Sequential breakout event index is noncontiguous."
            )
        if event.previous_event_id != previous_id:
            raise SequentialBreakoutError(
                "Sequential breakout predecessor event is contradictory."
            )
        if event.setup_sequence:
            previous_setup = setup_ids.get(event.setup_sequence)
            if previous_setup is not None and previous_setup != event.setup_id:
                raise SequentialBreakoutError(
                    "Sequential breakout setup sequence was reused."
                )
            if previous_setup is None:
                if event.setup_sequence != highest_setup_sequence + 1:
                    raise SequentialBreakoutError(
                        "Sequential breakout setup sequence is noncontiguous."
                    )
                highest_setup_sequence = event.setup_sequence
            setup_ids[event.setup_sequence] = event.setup_id
            if event.predecessor_setup_id:
                if event.predecessor_setup_id not in observed_setup_ids:
                    raise SequentialBreakoutError(
                        "Sequential breakout predecessor setup was not observed."
                    )
                if event.predecessor_setup_id == event.setup_id:
                    raise SequentialBreakoutError(
                        "Sequential breakout setup cannot precede itself."
                    )
                if (
                    event.event_type == RECLAIM_CONFIRMED
                    and event.predecessor_setup_id not in failed_setup_ids
                ):
                    raise SequentialBreakoutError(
                        "Sequential breakout reclaim lacks a prior failed breakout."
                    )
            observed_setup_ids.add(event.setup_id)
        if event.event_type == FAILED_BREAKOUT:
            failed_setup_ids.add(event.setup_id)
        previous_id = event.event_id
        previous_provider_time = provider_time


def validate_event(
    event: SequentialBreakoutEvent,
    *,
    policy: SequentialBreakoutPolicy,
) -> None:
    if event.schema_version != SEQUENTIAL_BREAKOUT_SCHEMA_VERSION:
        raise SequentialBreakoutError(
            "Sequential breakout event schema is unsupported."
        )
    if event.profile != SEQUENTIAL_BREAKOUT_PROFILE:
        raise SequentialBreakoutError(
            "Sequential breakout event profile is unsupported."
        )
    if event.event_type not in EVENT_TYPES:
        raise SequentialBreakoutError(
            "Sequential breakout event type is unsupported."
        )
    if event.authority != RESEARCH_ONLY or event.execution_authority is not False:
        raise SequentialBreakoutError(
            "Sequential breakout event attempted to gain execution authority."
        )
    if (
        not isinstance(event.event_index, int)
        or isinstance(event.event_index, bool)
        or event.event_index <= 0
    ):
        raise SequentialBreakoutError(
            "Sequential breakout event index must be positive."
        )
    if (
        event.policy_version != policy.policy_version
        or event.policy_fingerprint != policy.fingerprint
    ):
        raise SequentialBreakoutError(
            "Sequential breakout event policy identity is invalid."
        )
    if event.observation_mode not in OBSERVATION_MODES:
        raise SequentialBreakoutError(
            "Sequential breakout event observation mode is unsupported."
        )
    if event.source_state not in CANONICAL_OUTCOME_STATES:
        raise SequentialBreakoutError(
            "Sequential breakout event source state is not canonical."
        )
    if event.symbol != normalize_symbol(event.symbol):
        raise SequentialBreakoutError(
            "Sequential breakout event symbol is noncanonical."
        )
    normalized_session = normalize_session_date(event.session_date)
    require_text(event.source, "Candle source")
    require_text(event.reason, "Sequential breakout event reason")
    require_sha256(event.source_evidence_fingerprint, "Source evidence")
    require_sha256(event.event_id, "Sequential breakout event")
    require_sha256(event.fingerprint, "Sequential breakout event")
    if event.previous_event_id:
        require_sha256(event.previous_event_id, "Previous event")
    if event.predecessor_setup_id:
        require_sha256(event.predecessor_setup_id, "Predecessor setup")
    validate_event_numbers(event)
    validate_event_setup_semantics(event)
    if event.opportunity_id != expected_opportunity_id(
        event.symbol, event.session_date, event.originating_evidence_family
    ):
        raise SequentialBreakoutError(
            "Sequential breakout opportunity identity is invalid."
        )
    if event.setup_id:
        if event.setup_id != expected_setup_id(
            event.opportunity_id, event.setup_family, event.setup_sequence
        ):
            raise SequentialBreakoutError(
                "Sequential breakout setup identity is invalid."
            )
    elif event.setup_family or event.setup_sequence or event.predecessor_setup_id:
        raise SequentialBreakoutError(
            "Sequential breakout event has incomplete setup identity."
        )
    if event.event_id != expected_event_id(event):
        raise SequentialBreakoutError(
            "Sequential breakout event identity is invalid."
        )
    if event.fingerprint != event_fingerprint(event):
        raise SequentialBreakoutError(
            "Sequential breakout event fingerprint is invalid."
        )
    provider = aware_datetime(event.provider_timestamp)
    receipt = aware_datetime(event.receipt_timestamp)
    if receipt < provider:
        raise SequentialBreakoutError(
            "Sequential breakout event receipt precedes provider evidence."
        )
    if provider.astimezone(EASTERN_TZ).date().isoformat() != normalized_session:
        raise SequentialBreakoutError(
            "Sequential breakout event timestamp contradicts its market session."
        )


def validate_event_numbers(event: SequentialBreakoutEvent) -> None:
    positive_fields = (
        ("observed_price", event.observed_price),
        ("trigger_price", event.trigger_price),
        ("prior_range_value", event.prior_range_value),
    )
    for name, value in positive_fields:
        if value is None:
            continue
        number = finite_number(value, name)
        if number <= 0:
            raise SequentialBreakoutError(
                f"Sequential breakout {name} must be positive."
            )
    nonnegative_fields = (
        ("volume", event.volume),
        ("relative_volume", event.relative_volume),
    )
    for name, value in nonnegative_fields:
        if value is None:
            continue
        if finite_number(value, name) < 0:
            raise SequentialBreakoutError(
                f"Sequential breakout {name} cannot be negative."
            )
    if event.distance_from_trigger_pct is not None:
        finite_number(
            event.distance_from_trigger_pct, "distance_from_trigger_pct"
        )


def validate_event_setup_semantics(event: SequentialBreakoutEvent) -> None:
    if event.event_type in UNSCOPED_EVENT_TYPES:
        if (
            event.setup_id
            or event.setup_family
            or event.setup_sequence
            or event.predecessor_setup_id
        ):
            raise SequentialBreakoutError(
                "Unscoped sequential breakout event has setup identity."
            )
        return
    if event.event_type in BREAKOUT_EVENT_TYPES:
        if event.setup_family not in BREAKOUT_SETUP_FAMILIES:
            raise SequentialBreakoutError(
                "Breakout event has an incompatible setup family."
            )
        if event.predecessor_setup_id:
            raise SequentialBreakoutError(
                "Primary breakout event cannot replace a predecessor setup."
            )
        return
    if event.event_type == PULLBACK_FORMING:
        expected_family = PULLBACK
    elif event.event_type == RECLAIM_CONFIRMED:
        expected_family = RECLAIM
    else:
        raise SequentialBreakoutError(
            "Sequential breakout event semantics are unsupported."
        )
    if event.setup_family != expected_family or not event.predecessor_setup_id:
        raise SequentialBreakoutError(
            "Structural follow-on event has incomplete setup lineage."
        )


def opening_range_trigger(
    observations: Sequence[SequentialBreakoutObservation],
    policy: SequentialBreakoutPolicy,
) -> float | None:
    start = parsed_clock(policy.opening_range_start)
    end_minutes = (
        datetime.combine(date.min, start) + timedelta(minutes=policy.opening_range_bars)
    ).time()
    bars = [
        item
        for item in observations
        if start
        <= aware_datetime(item.provider_timestamp).astimezone(EASTERN_TZ).time()
        < end_minutes
    ]
    if len(bars) != policy.opening_range_bars:
        return None
    for prior, current in zip(bars, bars[1:]):
        if (
            aware_datetime(current.provider_timestamp)
            - aware_datetime(prior.provider_timestamp)
            != timedelta(minutes=1)
        ):
            return None
    return max(item.high for item in bars)


def baseline_range(
    observations: Sequence[SequentialBreakoutObservation],
    index: int,
    segment_start: int,
    window: int,
) -> float | None:
    if index - segment_start < window:
        return None
    values = [
        item.high - item.low
        for item in observations[index - window : index]
        if item.high > item.low
    ]
    if len(values) != window:
        return None
    value = statistics.median(values)
    return value if value > 0 else None


def prior_relative_volume(
    observations: Sequence[SequentialBreakoutObservation],
    index: int,
    segment_start: int,
    window: int,
) -> float | None:
    if index - segment_start < window:
        return None
    prior = [item.volume for item in observations[index - window : index]]
    if len(prior) != window or any(value < 0 for value in prior):
        return None
    average = sum(prior) / len(prior)
    if average <= 0:
        return None
    return current_ratio(observations[index].volume, average)


def current_ratio(current: float, average: float) -> float:
    return round(current / average, 4)


def policy_fingerprint(policy: SequentialBreakoutPolicy) -> str:
    validate_policy_fields(policy)
    return sha256_payload(asdict(policy))


def validate_policy(policy: SequentialBreakoutPolicy) -> None:
    validate_policy_fields(policy)
    if not require_text(policy.policy_version, "Research policy version"):
        raise SequentialBreakoutError("Research policy version is required.")
    parsed_clock(policy.opening_range_start)
    parsed_clock(policy.opening_breakout_cutoff)
    if parsed_clock(policy.opening_breakout_cutoff) <= parsed_clock(
        policy.opening_range_start
    ):
        raise SequentialBreakoutError(
            "Opening breakout cutoff must follow the opening-range start."
        )


def validate_policy_fields(policy: SequentialBreakoutPolicy) -> None:
    integer_fields = (
        "prior_range_bars",
        "opening_range_bars",
        "range_baseline_bars",
        "volume_baseline_bars",
        "impulse_window_bars",
        "max_sequence_bars",
    )
    for name in integer_fields:
        value = getattr(policy, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SequentialBreakoutError(f"Research policy {name} must be positive.")
    float_fields = (
        "impulse_range_multiple",
        "volume_confirmation_multiple",
        "missed_range_multiple",
        "pullback_range_multiple",
        "exhaustion_range_multiple",
    )
    for name in float_fields:
        value = getattr(policy, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise SequentialBreakoutError(f"Research policy {name} must be positive.")


def expected_event_id(event: SequentialBreakoutEvent) -> str:
    return stable_hash(
        "sequential-breakout-event-v1",
        event.opportunity_id,
        event.event_type,
        event.provider_timestamp,
        event.setup_id,
        event.source_evidence_fingerprint,
        event.policy_fingerprint,
    )


def event_fingerprint(event: SequentialBreakoutEvent) -> str:
    return sha256_payload(asdict(replace(event, fingerprint="")))


def observation_fingerprint(observation: SequentialBreakoutObservation) -> str:
    return sha256_payload(asdict(replace(observation, fingerprint="")))


def event_sort_key(event: SequentialBreakoutEvent) -> tuple[str, str, str, int]:
    return (
        event.session_date,
        event.symbol,
        event.opportunity_id,
        event.event_index,
    )


def ledger_to_wire(ledger: SequentialBreakoutLedger) -> dict[str, object]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "research_only": True,
        "execution_authority": False,
        "policy": asdict(ledger.policy),
        "events": [asdict(event) for event in ledger.events],
    }


def ledger_from_wire(payload: object) -> SequentialBreakoutLedger:
    if not isinstance(payload, Mapping):
        raise SequentialBreakoutError("Sequential breakout ledger is malformed.")
    if payload.get("research_only") is not True or payload.get("execution_authority") is not False:
        raise SequentialBreakoutError(
            "Sequential breakout ledger authority flags are invalid."
        )
    policy_payload = payload.get("policy")
    events_payload = payload.get("events")
    if not isinstance(policy_payload, Mapping) or not isinstance(events_payload, list):
        raise SequentialBreakoutError("Sequential breakout ledger fields are malformed.")
    try:
        policy = SequentialBreakoutPolicy(**dict(policy_payload))
        events = tuple(
            SequentialBreakoutEvent(**dict(item))
            for item in events_payload
            if isinstance(item, Mapping)
        )
    except (TypeError, ValueError) as exc:
        raise SequentialBreakoutError(
            "Sequential breakout ledger records are malformed."
        ) from exc
    if len(events) != len(events_payload):
        raise SequentialBreakoutError(
            "Sequential breakout ledger contains a malformed event."
        )
    return SequentialBreakoutLedger(
        policy=policy,
        events=events,
        schema_version=payload.get("schema_version"),
        profile=payload.get("profile"),
    )


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def validate_ohlcv(
    open_value: object,
    high_value: object,
    low_value: object,
    close_value: object,
    volume_value: object,
) -> dict[str, float]:
    values = {
        "open": finite_number(open_value, "open"),
        "high": finite_number(high_value, "high"),
        "low": finite_number(low_value, "low"),
        "close": finite_number(close_value, "close"),
        "volume": finite_number(volume_value, "volume"),
    }
    if min(values[name] for name in ("open", "high", "low", "close")) <= 0:
        raise SequentialBreakoutError("Sequential breakout prices must be positive.")
    if values["volume"] < 0:
        raise SequentialBreakoutError("Sequential breakout volume cannot be negative.")
    if values["high"] < max(values["open"], values["low"], values["close"]):
        raise SequentialBreakoutError("Sequential breakout high is invalid.")
    if values["low"] > min(values["open"], values["high"], values["close"]):
        raise SequentialBreakoutError("Sequential breakout low is invalid.")
    return values


def finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SequentialBreakoutError(
            f"Sequential breakout {label} must be numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise SequentialBreakoutError(
            f"Sequential breakout {label} must be finite."
        )
    return number


def normalize_session_date(value: object) -> str:
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise SequentialBreakoutError(
            "Sequential breakout session date is invalid."
        ) from exc


def require_sha256(value: object, label: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256_PATTERN.fullmatch(text):
        raise SequentialBreakoutError(f"{label} fingerprint is invalid.")
    return text


def require_text(value: object, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise SequentialBreakoutError(f"{label} is required.")
    return text


def aware_text(value: datetime | str, label: str) -> str:
    parsed = value if isinstance(value, datetime) else aware_datetime(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SequentialBreakoutError(f"{label} must include a UTC offset.")
    return parsed.isoformat()


def aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SequentialBreakoutError(
            "Sequential breakout timestamp is invalid."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SequentialBreakoutError(
            "Sequential breakout timestamps require a UTC offset."
        )
    return parsed


def parsed_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise SequentialBreakoutError(
            "Sequential breakout policy clock is invalid."
        ) from exc


def canonical_number(value: float) -> str:
    return format(float(value), ".12g")


def rounded(value: float | None, *, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def distance_pct(price: float, trigger: float | None) -> float | None:
    if trigger is None or trigger <= 0:
        return None
    return round((price - trigger) / trigger * 100.0, 6)
