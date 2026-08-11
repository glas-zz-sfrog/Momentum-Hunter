"""Deterministic outcome evidence for sequential breakout research.

This module is an offline, research-only consumer of BREAKOUT-001 evidence.
It measures forward same-session price behavior without fetching data, changing
candidate authority, creating a TradePlan, or contacting an execution provider.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from momentum_hunter.sequential_breakout_research import (
    BREAKOUT_CONFIRMED,
    HISTORICAL_REPLAY,
    PROSPECTIVE,
    RECLAIM_CONFIRMED,
    RESEARCH_ONLY,
    SequentialBreakoutEvent,
    SequentialBreakoutLedger,
    SequentialBreakoutObservation,
    aware_datetime,
    canonical_json_bytes,
    ledger_to_wire as source_ledger_to_wire,
    normalize_session_date,
    normalize_symbol,
    observation_fingerprint,
    sha256_payload,
    validate_ledger as validate_source_ledger,
    validate_observations,
)


BREAKOUT_OUTCOME_SCHEMA_VERSION = 1
BREAKOUT_OUTCOME_PROFILE = "sequential-breakout-outcomes-v1"
OUTCOME_PENDING = "PENDING"
OUTCOME_COMPLETE = "COMPLETE"
OUTCOME_GAP = "GAP"
OUTCOME_SESSION_UNAVAILABLE = "SESSION_UNAVAILABLE"
OUTCOME_STATES = frozenset(
    {
        OUTCOME_PENDING,
        OUTCOME_COMPLETE,
        OUTCOME_GAP,
        OUTCOME_SESSION_UNAVAILABLE,
    }
)
TERMINAL_OUTCOME_STATES = frozenset(
    {OUTCOME_COMPLETE, OUTCOME_GAP, OUTCOME_SESSION_UNAVAILABLE}
)

COHORT_THRESHOLD_UNSET = "COHORT_THRESHOLD_UNSET"
COHORT_INSUFFICIENT = "INSUFFICIENT_PROSPECTIVE_COHORT"
COHORT_READY_FOR_LATER_ADJUDICATION = "READY_FOR_LATER_ADJUDICATION"
COHORT_STATES = frozenset(
    {
        COHORT_THRESHOLD_UNSET,
        COHORT_INSUFFICIENT,
        COHORT_READY_FOR_LATER_ADJUDICATION,
    }
)

ELIGIBLE_ANCHOR_EVENTS = frozenset({BREAKOUT_CONFIRMED, RECLAIM_CONFIRMED})
OBSERVATION_MODES = frozenset({PROSPECTIVE, HISTORICAL_REPLAY})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class SequentialBreakoutOutcomeError(ValueError):
    """Raised when outcome evidence is invalid, contradictory, or tampered."""


@dataclass(frozen=True)
class SequentialBreakoutOutcomePolicy:
    """Versioned research mechanics, not a trading or calibration policy."""

    policy_version: str = "sequential-breakout-outcome-policy-v1"
    horizons_minutes: tuple[int, ...] = (5, 15, 30, 60)
    expected_bar_seconds: int = 60
    session_end_time: str = "16:00"
    minimum_prospective_events: int | None = None

    @property
    def fingerprint(self) -> str:
        return outcome_policy_fingerprint(self)


@dataclass(frozen=True)
class SequentialBreakoutOutcome:
    outcome_key: str
    outcome_id: str
    fingerprint: str
    revision: int
    previous_outcome_id: str
    corrected: bool
    source_event_chain_fingerprint: str
    source_event_id: str
    source_event_fingerprint: str
    source_breakout_policy_fingerprint: str
    opportunity_id: str
    setup_id: str
    setup_family: str
    event_type: str
    symbol: str
    session_date: str
    observation_mode: str
    event_provider_timestamp: str
    event_receipt_timestamp: str
    target_provider_timestamp: str
    first_observed_at: str
    horizon_minutes: int
    status: str
    expected_bar_count: int
    observed_bar_count: int
    source_bar_timestamps: tuple[str, ...]
    source_bar_fingerprints: tuple[str, ...]
    source_set: tuple[str, ...]
    anchor_price: float | None
    trigger_price: float | None
    outcome_close: float | None
    forward_return_pct: float | None
    max_favorable_excursion_pct: float | None
    max_adverse_excursion_pct: float | None
    held_above_trigger: bool | None
    failed_below_trigger: bool | None
    first_failure_timestamp: str
    event_relative_volume: float | None
    reason: str
    authority: str = RESEARCH_ONLY
    execution_authority: bool = False
    conclusion_authority: bool = False
    schema_version: int = BREAKOUT_OUTCOME_SCHEMA_VERSION
    profile: str = BREAKOUT_OUTCOME_PROFILE


@dataclass(frozen=True)
class SequentialBreakoutOutcomeLedger:
    policy: SequentialBreakoutOutcomePolicy
    outcomes: tuple[SequentialBreakoutOutcome, ...] = field(default_factory=tuple)
    schema_version: int = BREAKOUT_OUTCOME_SCHEMA_VERSION
    profile: str = BREAKOUT_OUTCOME_PROFILE


@dataclass(frozen=True)
class BreakoutCohortHorizonSummary:
    observation_mode: str
    horizon_minutes: int
    eligible_event_count: int
    complete_count: int
    pending_count: int
    gap_count: int
    session_unavailable_count: int
    missing_outcome_count: int
    positive_return_count: int
    failed_below_trigger_count: int
    mean_forward_return_pct: float | None
    median_forward_return_pct: float | None
    positive_return_rate_pct: float | None
    failed_below_trigger_rate_pct: float | None


@dataclass(frozen=True)
class SequentialBreakoutCohortSnapshot:
    cohort_id: str
    fingerprint: str
    source_ledger_fingerprint: str
    policy_version: str
    policy_fingerprint: str
    created_at: str
    source_event_count: int
    eligible_anchor_event_count: int
    ineligible_source_event_count: int
    prospective_anchor_event_count: int
    historical_anchor_event_count: int
    minimum_prospective_events: int | None
    cohort_status: str
    conclusions_authorized: bool
    latest_outcome_fingerprints: tuple[str, ...]
    summaries: tuple[BreakoutCohortHorizonSummary, ...]
    authority: str = RESEARCH_ONLY
    execution_authority: bool = False
    schema_version: int = BREAKOUT_OUTCOME_SCHEMA_VERSION
    profile: str = BREAKOUT_OUTCOME_PROFILE


class SequentialBreakoutOutcomeStore:
    """Explicit-path append-only outcome ledger with atomic replacement."""

    def __init__(
        self,
        path: Path,
        *,
        policy: SequentialBreakoutOutcomePolicy,
    ) -> None:
        validate_outcome_policy(policy)
        self.path = path
        self.policy = policy

    def load(self) -> SequentialBreakoutOutcomeLedger:
        if not self.path.exists():
            return SequentialBreakoutOutcomeLedger(policy=self.policy)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SequentialBreakoutOutcomeError(
                f"Sequential breakout outcome evidence cannot be loaded: {type(exc).__name__}"
            ) from exc
        ledger = outcome_ledger_from_wire(payload)
        validate_outcome_ledger(ledger)
        if ledger.policy != self.policy:
            raise SequentialBreakoutOutcomeError(
                "Sequential breakout outcome policy conflicts with stored evidence."
            )
        return ledger

    def append(
        self,
        outcomes: Iterable[SequentialBreakoutOutcome],
    ) -> SequentialBreakoutOutcomeLedger:
        current = self.load()
        by_id = {outcome.outcome_id: outcome for outcome in current.outcomes}
        latest_by_key = latest_outcomes(current.outcomes)
        changed = False
        for outcome in outcomes:
            validate_outcome(outcome, policy=self.policy)
            existing = by_id.get(outcome.outcome_id)
            if existing is not None:
                if existing != outcome:
                    raise SequentialBreakoutOutcomeError(
                        "Sequential breakout outcome identity conflicts with stored evidence."
                    )
                continue
            latest = latest_by_key.get(outcome.outcome_key)
            if latest is None:
                if outcome.revision != 1 or outcome.previous_outcome_id:
                    raise SequentialBreakoutOutcomeError(
                        "Initial sequential breakout outcome revision is invalid."
                    )
            elif (
                outcome.revision != latest.revision + 1
                or outcome.previous_outcome_id != latest.outcome_id
            ):
                raise SequentialBreakoutOutcomeError(
                    "Sequential breakout outcome revision branched from stale evidence."
                )
            by_id[outcome.outcome_id] = outcome
            latest_by_key[outcome.outcome_key] = outcome
            changed = True
        updated = replace(
            current,
            outcomes=tuple(sorted(by_id.values(), key=outcome_sort_key)),
        )
        validate_outcome_ledger(updated)
        if changed:
            self._save(updated)
        return updated

    def _save(self, ledger: SequentialBreakoutOutcomeLedger) -> None:
        content = canonical_json_bytes(outcome_ledger_to_wire(ledger))
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


def build_outcome_assessments(
    source_ledger: SequentialBreakoutLedger,
    observations_by_identity: Mapping[
        tuple[str, str], Sequence[SequentialBreakoutObservation]
    ],
    *,
    as_of: datetime | str,
    policy: SequentialBreakoutOutcomePolicy | None = None,
    previous_outcomes: Sequence[SequentialBreakoutOutcome] = (),
) -> tuple[SequentialBreakoutOutcome, ...]:
    """Assess every eligible event/horizon without hiding unavailable rows."""

    selected_policy = policy or SequentialBreakoutOutcomePolicy()
    validate_outcome_policy(selected_policy)
    validate_source_ledger(source_ledger)
    as_of_text = aware_text(as_of, "Outcome as-of timestamp")
    as_of_time = aware_datetime(as_of_text)
    normalized_observations = normalize_observation_map(
        observations_by_identity,
        as_of_time=as_of_time,
    )
    latest_previous = latest_outcomes(previous_outcomes)
    for previous in previous_outcomes:
        validate_outcome(previous, policy=selected_policy)

    results: list[SequentialBreakoutOutcome] = []
    for event in source_ledger.events:
        if event.event_type not in ELIGIBLE_ANCHOR_EVENTS:
            continue
        event_observations = normalized_observations.get(
            (event.symbol, event.session_date), ()
        )
        for horizon in selected_policy.horizons_minutes:
            key = expected_outcome_key(event, horizon, selected_policy)
            results.append(
                assess_outcome(
                    event,
                    event_observations,
                    as_of=as_of_text,
                    source_event_chain_fingerprint=source_event_chain_fingerprint(
                        source_ledger, event
                    ),
                    policy=selected_policy,
                    horizon_minutes=horizon,
                    previous=latest_previous.get(key),
                )
            )
    return tuple(sorted(results, key=outcome_sort_key))


def assess_outcome(
    event: SequentialBreakoutEvent,
    observations: Sequence[SequentialBreakoutObservation],
    *,
    as_of: datetime | str,
    source_event_chain_fingerprint: str,
    policy: SequentialBreakoutOutcomePolicy,
    horizon_minutes: int | None = None,
    previous: SequentialBreakoutOutcome | None = None,
) -> SequentialBreakoutOutcome:
    """Build one deterministic outcome revision for one event and horizon."""

    validate_outcome_policy(policy)
    require_sha256(source_event_chain_fingerprint, "Source event chain")
    if event.event_type not in ELIGIBLE_ANCHOR_EVENTS:
        raise SequentialBreakoutOutcomeError(
            "Sequential breakout event is not an eligible outcome anchor."
        )
    selected_horizon = (
        policy.horizons_minutes[0] if horizon_minutes is None else horizon_minutes
    )
    if selected_horizon not in policy.horizons_minutes:
        raise SequentialBreakoutOutcomeError(
            "Sequential breakout outcome horizon is not in the frozen policy."
        )
    as_of_text = aware_text(as_of, "Outcome as-of timestamp")
    as_of_time = aware_datetime(as_of_text)
    event_time = aware_datetime(event.provider_timestamp)
    if as_of_time < event_time:
        raise SequentialBreakoutOutcomeError(
            "Sequential breakout outcome as-of precedes the source event."
        )
    normalized = tuple(observations)
    if normalized:
        validate_observations(normalized)
        if (
            normalized[0].symbol != event.symbol
            or normalized[0].session_date != event.session_date
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome observations crossed source event identity."
            )
        if any(
            observation.observation_mode != event.observation_mode
            for observation in normalized
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome observations crossed source event observation mode."
            )
        if any(
            aware_datetime(observation.receipt_timestamp) > as_of_time
            for observation in normalized
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome observations were received after the as-of timestamp."
            )

    target_time = event_time + timedelta(minutes=selected_horizon)
    status, selected_bars, reason = outcome_window_state(
        event,
        normalized,
        target_time=target_time,
        as_of_time=as_of_time,
        policy=policy,
    )
    values = outcome_values(event, selected_bars, status=status)
    key = expected_outcome_key(event, selected_horizon, policy)
    source_fingerprints = tuple(
        observation_fingerprint(observation) for observation in selected_bars
    )
    sources = tuple(sorted({observation.source for observation in selected_bars}))
    base = SequentialBreakoutOutcome(
        outcome_key=key,
        outcome_id="",
        fingerprint="",
        revision=1,
        previous_outcome_id="",
        corrected=False,
        source_event_chain_fingerprint=source_event_chain_fingerprint,
        source_event_id=event.event_id,
        source_event_fingerprint=event.fingerprint,
        source_breakout_policy_fingerprint=event.policy_fingerprint,
        opportunity_id=event.opportunity_id,
        setup_id=event.setup_id,
        setup_family=event.setup_family,
        event_type=event.event_type,
        symbol=event.symbol,
        session_date=event.session_date,
        observation_mode=event.observation_mode,
        event_provider_timestamp=event.provider_timestamp,
        event_receipt_timestamp=event.receipt_timestamp,
        target_provider_timestamp=target_time.isoformat(),
        first_observed_at=as_of_text,
        horizon_minutes=selected_horizon,
        status=status,
        expected_bar_count=selected_horizon,
        observed_bar_count=len(selected_bars),
        source_bar_timestamps=tuple(
            observation.provider_timestamp for observation in selected_bars
        ),
        source_bar_fingerprints=source_fingerprints,
        source_set=sources,
        anchor_price=event.observed_price,
        trigger_price=event.trigger_price,
        outcome_close=values["outcome_close"],
        forward_return_pct=values["forward_return_pct"],
        max_favorable_excursion_pct=values["mfe"],
        max_adverse_excursion_pct=values["mae"],
        held_above_trigger=values["held"],
        failed_below_trigger=values["failed"],
        first_failure_timestamp=values["first_failure_timestamp"],
        event_relative_volume=event.relative_volume,
        reason=reason,
    )
    if previous is not None:
        validate_outcome(previous, policy=policy)
        if previous.outcome_key != key:
            raise SequentialBreakoutOutcomeError(
                "Previous outcome belongs to another event or horizon."
            )
        if as_of_time < aware_datetime(previous.first_observed_at):
            raise SequentialBreakoutOutcomeError(
                "Outcome revision chronology cannot move backward."
            )
        if material_outcome_payload(previous) == material_outcome_payload(base):
            return previous
        if previous.status == OUTCOME_SESSION_UNAVAILABLE:
            raise SequentialBreakoutOutcomeError(
                "Session-unavailable outcome evidence is terminal."
            )
        if previous.status == OUTCOME_COMPLETE and status != OUTCOME_COMPLETE:
            raise SequentialBreakoutOutcomeError(
                "Completed outcome evidence cannot regress to an incomplete state."
            )
        base = replace(
            base,
            revision=previous.revision + 1,
            previous_outcome_id=previous.outcome_id,
            corrected=previous.status in TERMINAL_OUTCOME_STATES,
        )
    outcome_id = expected_outcome_id(base)
    completed = replace(base, outcome_id=outcome_id)
    completed = replace(completed, fingerprint=outcome_fingerprint(completed))
    validate_outcome(completed, policy=policy)
    return completed


def build_cohort_snapshot(
    source_ledger: SequentialBreakoutLedger,
    outcomes: Sequence[SequentialBreakoutOutcome],
    *,
    created_at: datetime | str,
    policy: SequentialBreakoutOutcomePolicy,
) -> SequentialBreakoutCohortSnapshot:
    """Build descriptive evidence while withholding any edge conclusion."""

    validate_source_ledger(source_ledger)
    validate_outcome_policy(policy)
    created_text = aware_text(created_at, "Cohort creation timestamp")
    latest = latest_outcomes(outcomes)
    for outcome in outcomes:
        validate_outcome(outcome, policy=policy)
    eligible = tuple(
        event
        for event in source_ledger.events
        if event.event_type in ELIGIBLE_ANCHOR_EVENTS
    )
    expected_keys = {
        expected_outcome_key(event, horizon, policy)
        for event in eligible
        for horizon in policy.horizons_minutes
    }
    unknown = set(latest) - expected_keys
    if unknown:
        raise SequentialBreakoutOutcomeError(
            "Outcome cohort contains evidence outside the source event ledger."
        )
    source_fingerprint = source_breakout_ledger_fingerprint(source_ledger)
    event_by_id = {event.event_id: event for event in eligible}
    for outcome in latest.values():
        event = event_by_id.get(outcome.source_event_id)
        if event is None:
            raise SequentialBreakoutOutcomeError(
                "Outcome cohort source event is absent from the source ledger."
            )
        validate_outcome_against_event(
            outcome,
            event,
            source_event_chain_fingerprint=source_event_chain_fingerprint(
                source_ledger, event
            ),
        )

    summaries = tuple(
        build_horizon_summary(
            eligible,
            latest,
            observation_mode=mode,
            horizon_minutes=horizon,
            policy=policy,
        )
        for mode in (PROSPECTIVE, HISTORICAL_REPLAY)
        for horizon in policy.horizons_minutes
    )
    prospective_ids = {
        event.event_id for event in eligible if event.observation_mode == PROSPECTIVE
    }
    historical_ids = {
        event.event_id
        for event in eligible
        if event.observation_mode == HISTORICAL_REPLAY
    }
    prospective_terminal = all(
        (
            key := expected_outcome_key(event, horizon, policy)
        ) in latest
        and latest[key].status in TERMINAL_OUTCOME_STATES
        for event in eligible
        if event.observation_mode == PROSPECTIVE
        for horizon in policy.horizons_minutes
    )
    if policy.minimum_prospective_events is None:
        cohort_status = COHORT_THRESHOLD_UNSET
    elif (
        len(prospective_ids) < policy.minimum_prospective_events
        or not prospective_terminal
    ):
        cohort_status = COHORT_INSUFFICIENT
    else:
        cohort_status = COHORT_READY_FOR_LATER_ADJUDICATION
    draft = SequentialBreakoutCohortSnapshot(
        cohort_id="",
        fingerprint="",
        source_ledger_fingerprint=source_fingerprint,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
        created_at=created_text,
        source_event_count=len(source_ledger.events),
        eligible_anchor_event_count=len(eligible),
        ineligible_source_event_count=len(source_ledger.events) - len(eligible),
        prospective_anchor_event_count=len(prospective_ids),
        historical_anchor_event_count=len(historical_ids),
        minimum_prospective_events=policy.minimum_prospective_events,
        cohort_status=cohort_status,
        conclusions_authorized=False,
        latest_outcome_fingerprints=tuple(
            sorted(outcome.fingerprint for outcome in latest.values())
        ),
        summaries=summaries,
    )
    cohort_id = expected_cohort_id(draft)
    completed = replace(draft, cohort_id=cohort_id)
    completed = replace(completed, fingerprint=cohort_fingerprint(completed))
    validate_cohort_snapshot(completed, policy=policy)
    return completed


def build_horizon_summary(
    eligible_events: Sequence[SequentialBreakoutEvent],
    latest: Mapping[str, SequentialBreakoutOutcome],
    *,
    observation_mode: str,
    horizon_minutes: int,
    policy: SequentialBreakoutOutcomePolicy,
) -> BreakoutCohortHorizonSummary:
    events = tuple(
        event for event in eligible_events if event.observation_mode == observation_mode
    )
    records = tuple(
        latest[key]
        for event in events
        if (key := expected_outcome_key(event, horizon_minutes, policy)) in latest
    )
    by_status = {state: 0 for state in OUTCOME_STATES}
    for record in records:
        by_status[record.status] += 1
    completed = tuple(
        record for record in records if record.status == OUTCOME_COMPLETE
    )
    returns = tuple(
        require_finite(record.forward_return_pct, "Forward return")
        for record in completed
    )
    positive = sum(value > 0.0 for value in returns)
    failed = sum(record.failed_below_trigger is True for record in completed)
    missing = len(events) - len(records)
    return BreakoutCohortHorizonSummary(
        observation_mode=observation_mode,
        horizon_minutes=horizon_minutes,
        eligible_event_count=len(events),
        complete_count=len(completed),
        pending_count=by_status[OUTCOME_PENDING],
        gap_count=by_status[OUTCOME_GAP],
        session_unavailable_count=by_status[OUTCOME_SESSION_UNAVAILABLE],
        missing_outcome_count=missing,
        positive_return_count=positive,
        failed_below_trigger_count=failed,
        mean_forward_return_pct=rounded(statistics.fmean(returns)) if returns else None,
        median_forward_return_pct=rounded(statistics.median(returns)) if returns else None,
        positive_return_rate_pct=rounded(positive * 100.0 / len(returns))
        if returns
        else None,
        failed_below_trigger_rate_pct=rounded(failed * 100.0 / len(returns))
        if returns
        else None,
    )


def outcome_window_state(
    event: SequentialBreakoutEvent,
    observations: Sequence[SequentialBreakoutObservation],
    *,
    target_time: datetime,
    as_of_time: datetime,
    policy: SequentialBreakoutOutcomePolicy,
) -> tuple[str, tuple[SequentialBreakoutObservation, ...], str]:
    event_time = aware_datetime(event.provider_timestamp)
    session_end = event_time.replace(
        hour=parsed_clock(policy.session_end_time).hour,
        minute=parsed_clock(policy.session_end_time).minute,
        second=0,
        microsecond=0,
    )
    if target_time > session_end:
        return (
            OUTCOME_SESSION_UNAVAILABLE,
            (),
            "Requested horizon extends beyond the frozen same-session boundary.",
        )
    if as_of_time < target_time:
        return (
            OUTCOME_PENDING,
            (),
            "Requested horizon has not elapsed; no partial metric is reported.",
        )
    expected_times = tuple(
        event_time + timedelta(seconds=policy.expected_bar_seconds * index)
        for index in range(1, int((target_time - event_time).total_seconds() // policy.expected_bar_seconds) + 1)
    )
    by_time = {
        aware_datetime(observation.provider_timestamp): observation
        for observation in observations
        if event_time < aware_datetime(observation.provider_timestamp) <= target_time
    }
    selected = tuple(by_time[value] for value in expected_times if value in by_time)
    if len(selected) != len(expected_times):
        missing = len(expected_times) - len(selected)
        return (
            OUTCOME_GAP,
            selected,
            f"Outcome window is missing {missing} completed canonical bar(s).",
        )
    return (
        OUTCOME_COMPLETE,
        selected,
        "Exact completed same-session outcome window is available.",
    )


def outcome_values(
    event: SequentialBreakoutEvent,
    bars: Sequence[SequentialBreakoutObservation],
    *,
    status: str,
) -> dict[str, object]:
    empty: dict[str, object] = {
        "outcome_close": None,
        "forward_return_pct": None,
        "mfe": None,
        "mae": None,
        "held": None,
        "failed": None,
        "first_failure_timestamp": "",
    }
    if status != OUTCOME_COMPLETE:
        return empty
    anchor = require_positive(event.observed_price, "Event observed price")
    trigger = require_positive(event.trigger_price, "Event trigger price")
    outcome_close = bars[-1].close
    failed_bars = tuple(bar for bar in bars if bar.low < trigger)
    return {
        "outcome_close": rounded(outcome_close),
        "forward_return_pct": rounded(percent_change(outcome_close, anchor)),
        "mfe": rounded(max(percent_change(bar.high, anchor) for bar in bars)),
        "mae": rounded(min(percent_change(bar.low, anchor) for bar in bars)),
        "held": not failed_bars,
        "failed": bool(failed_bars),
        "first_failure_timestamp": failed_bars[0].provider_timestamp
        if failed_bars
        else "",
    }


def normalize_observation_map(
    observations_by_identity: Mapping[
        tuple[str, str], Sequence[SequentialBreakoutObservation]
    ],
    *,
    as_of_time: datetime,
) -> dict[tuple[str, str], tuple[SequentialBreakoutObservation, ...]]:
    normalized: dict[tuple[str, str], tuple[SequentialBreakoutObservation, ...]] = {}
    for raw_key, observations in observations_by_identity.items():
        if not isinstance(raw_key, tuple) or len(raw_key) != 2:
            raise SequentialBreakoutOutcomeError(
                "Outcome observation map key must be (symbol, session_date)."
            )
        key = (normalize_symbol(raw_key[0]), normalize_session_date(raw_key[1]))
        values = tuple(observations)
        if values:
            validate_observations(values)
            if (values[0].symbol, values[0].session_date) != key:
                raise SequentialBreakoutOutcomeError(
                    "Outcome observation map key contradicts its evidence."
                )
            if any(
                aware_datetime(value.receipt_timestamp) > as_of_time
                for value in values
            ):
                raise SequentialBreakoutOutcomeError(
                    "Outcome observations were received after the as-of timestamp."
                )
        if key in normalized:
            raise SequentialBreakoutOutcomeError(
                "Outcome observation map identity is duplicated."
            )
        normalized[key] = values
    return normalized


def validate_outcome_policy(policy: SequentialBreakoutOutcomePolicy) -> None:
    require_text(policy.policy_version, "Outcome policy version")
    if not policy.horizons_minutes:
        raise SequentialBreakoutOutcomeError(
            "Outcome policy requires at least one horizon."
        )
    if tuple(sorted(set(policy.horizons_minutes))) != policy.horizons_minutes:
        raise SequentialBreakoutOutcomeError(
            "Outcome policy horizons must be unique and increasing."
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in policy.horizons_minutes
    ):
        raise SequentialBreakoutOutcomeError(
            "Outcome policy horizons must be positive whole minutes."
        )
    if policy.expected_bar_seconds != 60:
        raise SequentialBreakoutOutcomeError(
            "Synthetic outcome contract currently requires exact one-minute bars."
        )
    parsed_clock(policy.session_end_time)
    minimum = policy.minimum_prospective_events
    if minimum is not None and (
        not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0
    ):
        raise SequentialBreakoutOutcomeError(
            "Minimum prospective cohort size must be positive when configured."
        )


def validate_outcome(
    outcome: SequentialBreakoutOutcome,
    *,
    policy: SequentialBreakoutOutcomePolicy,
) -> None:
    validate_outcome_policy(policy)
    if outcome.schema_version != BREAKOUT_OUTCOME_SCHEMA_VERSION:
        raise SequentialBreakoutOutcomeError("Outcome schema is unsupported.")
    if outcome.profile != BREAKOUT_OUTCOME_PROFILE:
        raise SequentialBreakoutOutcomeError("Outcome profile is unsupported.")
    if (
        outcome.authority != RESEARCH_ONLY
        or outcome.execution_authority is not False
        or outcome.conclusion_authority is not False
    ):
        raise SequentialBreakoutOutcomeError(
            "Sequential breakout outcome attempted to gain authority."
        )
    if outcome.status not in OUTCOME_STATES:
        raise SequentialBreakoutOutcomeError("Outcome status is unsupported.")
    if outcome.observation_mode not in OBSERVATION_MODES:
        raise SequentialBreakoutOutcomeError(
            "Outcome observation mode is unsupported."
        )
    if outcome.event_type not in ELIGIBLE_ANCHOR_EVENTS:
        raise SequentialBreakoutOutcomeError("Outcome event type is unsupported.")
    if outcome.horizon_minutes not in policy.horizons_minutes:
        raise SequentialBreakoutOutcomeError("Outcome horizon is not in policy.")
    if outcome.expected_bar_count != outcome.horizon_minutes:
        raise SequentialBreakoutOutcomeError("Outcome expected bar count is invalid.")
    if (
        not isinstance(outcome.observed_bar_count, int)
        or isinstance(outcome.observed_bar_count, bool)
        or outcome.observed_bar_count < 0
        or outcome.observed_bar_count > outcome.expected_bar_count
        or outcome.observed_bar_count != len(outcome.source_bar_timestamps)
        or outcome.observed_bar_count != len(outcome.source_bar_fingerprints)
    ):
        raise SequentialBreakoutOutcomeError("Outcome observed bar count is invalid.")
    if outcome.revision <= 0 or isinstance(outcome.revision, bool):
        raise SequentialBreakoutOutcomeError("Outcome revision is invalid.")
    if (outcome.revision == 1) != (outcome.previous_outcome_id == ""):
        raise SequentialBreakoutOutcomeError("Outcome predecessor identity is invalid.")
    if outcome.corrected and outcome.revision == 1:
        raise SequentialBreakoutOutcomeError("Initial outcome cannot be corrected.")
    for value, label in (
        (outcome.outcome_key, "Outcome key"),
        (outcome.outcome_id, "Outcome ID"),
        (outcome.fingerprint, "Outcome"),
        (outcome.source_event_chain_fingerprint, "Source event chain"),
        (outcome.source_event_id, "Source event"),
        (outcome.source_event_fingerprint, "Source event"),
        (outcome.source_breakout_policy_fingerprint, "Source breakout policy"),
        (outcome.opportunity_id, "Opportunity"),
        (outcome.setup_id, "Setup"),
    ):
        require_sha256(value, label)
    if outcome.previous_outcome_id:
        require_sha256(outcome.previous_outcome_id, "Previous outcome")
    for fingerprint in outcome.source_bar_fingerprints:
        require_sha256(fingerprint, "Source bar")
    if len(set(outcome.source_bar_fingerprints)) != len(
        outcome.source_bar_fingerprints
    ):
        raise SequentialBreakoutOutcomeError(
            "Outcome source bar fingerprints are duplicated."
        )
    if outcome.symbol != normalize_symbol(outcome.symbol):
        raise SequentialBreakoutOutcomeError("Outcome symbol is noncanonical.")
    if outcome.session_date != normalize_session_date(outcome.session_date):
        raise SequentialBreakoutOutcomeError("Outcome session is noncanonical.")
    if tuple(sorted(set(outcome.source_set))) != outcome.source_set:
        raise SequentialBreakoutOutcomeError("Outcome source set is noncanonical.")
    for source in outcome.source_set:
        require_text(source, "Outcome source")
    require_text(outcome.reason, "Outcome reason")
    event_time = aware_datetime(outcome.event_provider_timestamp)
    receipt_time = aware_datetime(outcome.event_receipt_timestamp)
    target_time = aware_datetime(outcome.target_provider_timestamp)
    first_observed = aware_datetime(outcome.first_observed_at)
    if receipt_time < event_time or first_observed < event_time:
        raise SequentialBreakoutOutcomeError("Outcome chronology is invalid.")
    if target_time != event_time + timedelta(minutes=outcome.horizon_minutes):
        raise SequentialBreakoutOutcomeError("Outcome target timestamp is invalid.")
    source_times = tuple(
        aware_datetime(value) for value in outcome.source_bar_timestamps
    )
    if source_times != tuple(sorted(set(source_times))):
        raise SequentialBreakoutOutcomeError(
            "Outcome source bar timestamps are duplicated or nonchronological."
        )
    if any(value <= event_time or value > target_time for value in source_times):
        raise SequentialBreakoutOutcomeError(
            "Outcome source bar timestamp is outside its exact horizon."
        )
    expected_times = tuple(
        event_time + timedelta(seconds=policy.expected_bar_seconds * index)
        for index in range(1, outcome.horizon_minutes + 1)
    )
    if any(value not in expected_times for value in source_times):
        raise SequentialBreakoutOutcomeError(
            "Outcome source bar timestamp is not minute-aligned to its event."
        )
    require_positive(outcome.anchor_price, "Outcome anchor price")
    require_positive(outcome.trigger_price, "Outcome trigger price")
    if outcome.event_relative_volume is not None:
        relative_volume = require_finite(
            outcome.event_relative_volume, "Event relative volume"
        )
        if relative_volume < 0:
            raise SequentialBreakoutOutcomeError(
                "Event relative volume cannot be negative."
            )
    if outcome.outcome_key != expected_outcome_key_from_record(outcome, policy):
        raise SequentialBreakoutOutcomeError("Outcome key is invalid.")
    if outcome.outcome_id != expected_outcome_id(outcome):
        raise SequentialBreakoutOutcomeError("Outcome ID is invalid.")
    if outcome.fingerprint != outcome_fingerprint(outcome):
        raise SequentialBreakoutOutcomeError("Outcome fingerprint is invalid.")
    validate_outcome_metrics(outcome)


def validate_outcome_metrics(outcome: SequentialBreakoutOutcome) -> None:
    metric_values = (
        outcome.outcome_close,
        outcome.forward_return_pct,
        outcome.max_favorable_excursion_pct,
        outcome.max_adverse_excursion_pct,
    )
    if outcome.status == OUTCOME_COMPLETE:
        if outcome.observed_bar_count != outcome.expected_bar_count:
            raise SequentialBreakoutOutcomeError(
                "Complete outcome lacks its exact bar window."
            )
        if tuple(
            aware_datetime(value) for value in outcome.source_bar_timestamps
        ) != tuple(
            aware_datetime(outcome.event_provider_timestamp)
            + timedelta(minutes=index)
            for index in range(1, outcome.horizon_minutes + 1)
        ):
            raise SequentialBreakoutOutcomeError(
                "Complete outcome has a noncontiguous bar window."
            )
        if any(value is None for value in metric_values):
            raise SequentialBreakoutOutcomeError(
                "Complete outcome is missing a deterministic metric."
            )
        if outcome.held_above_trigger is not (not outcome.failed_below_trigger):
            raise SequentialBreakoutOutcomeError(
                "Outcome hold/failure flags are contradictory."
            )
        if bool(outcome.first_failure_timestamp) is not bool(
            outcome.failed_below_trigger
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome failure timestamp is contradictory."
            )
        if outcome.first_failure_timestamp:
            failure_time = aware_datetime(outcome.first_failure_timestamp)
            if failure_time not in tuple(
                aware_datetime(value) for value in outcome.source_bar_timestamps
            ):
                raise SequentialBreakoutOutcomeError(
                    "Outcome failure timestamp is outside its source bars."
                )
        anchor = require_positive(outcome.anchor_price, "Outcome anchor price")
        outcome_close = require_positive(outcome.outcome_close, "Outcome close")
        if outcome.forward_return_pct != rounded(
            percent_change(outcome_close, anchor)
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome forward return contradicts its anchor and close."
            )
        if require_finite(
            outcome.max_favorable_excursion_pct, "Maximum favorable excursion"
        ) < require_finite(
            outcome.max_adverse_excursion_pct, "Maximum adverse excursion"
        ):
            raise SequentialBreakoutOutcomeError(
                "Outcome excursion bounds are contradictory."
            )
    else:
        if any(value is not None for value in metric_values) or any(
            value is not None
            for value in (outcome.held_above_trigger, outcome.failed_below_trigger)
        ):
            raise SequentialBreakoutOutcomeError(
                "Incomplete outcome fabricated performance metrics."
            )
        if outcome.first_failure_timestamp:
            raise SequentialBreakoutOutcomeError(
                "Incomplete outcome fabricated a failure timestamp."
            )
        if outcome.status == OUTCOME_PENDING and outcome.observed_bar_count:
            raise SequentialBreakoutOutcomeError(
                "Pending outcome must not preserve partial performance bars."
            )
        if outcome.status == OUTCOME_SESSION_UNAVAILABLE and outcome.observed_bar_count:
            raise SequentialBreakoutOutcomeError(
                "Session-unavailable outcome cannot preserve forward bars."
            )


def validate_outcome_ledger(ledger: SequentialBreakoutOutcomeLedger) -> None:
    if ledger.schema_version != BREAKOUT_OUTCOME_SCHEMA_VERSION:
        raise SequentialBreakoutOutcomeError("Outcome ledger schema is unsupported.")
    if ledger.profile != BREAKOUT_OUTCOME_PROFILE:
        raise SequentialBreakoutOutcomeError("Outcome ledger profile is unsupported.")
    validate_outcome_policy(ledger.policy)
    if tuple(sorted(ledger.outcomes, key=outcome_sort_key)) != ledger.outcomes:
        raise SequentialBreakoutOutcomeError("Outcome ledger order is noncanonical.")
    seen_ids: set[str] = set()
    chains: dict[str, list[SequentialBreakoutOutcome]] = {}
    for outcome in ledger.outcomes:
        validate_outcome(outcome, policy=ledger.policy)
        if outcome.outcome_id in seen_ids:
            raise SequentialBreakoutOutcomeError("Outcome ID is duplicated.")
        seen_ids.add(outcome.outcome_id)
        chains.setdefault(outcome.outcome_key, []).append(outcome)
    for records in chains.values():
        for index, record in enumerate(records, start=1):
            if record.revision != index:
                raise SequentialBreakoutOutcomeError(
                    "Outcome revision chain is noncontiguous."
                )
            expected_previous = records[index - 2].outcome_id if index > 1 else ""
            if record.previous_outcome_id != expected_previous:
                raise SequentialBreakoutOutcomeError(
                    "Outcome predecessor chain is contradictory."
                )
            if index > 1 and aware_datetime(
                record.first_observed_at
            ) < aware_datetime(records[index - 2].first_observed_at):
                raise SequentialBreakoutOutcomeError(
                    "Outcome revision chronology moved backward."
                )


def validate_cohort_snapshot(
    snapshot: SequentialBreakoutCohortSnapshot,
    *,
    policy: SequentialBreakoutOutcomePolicy,
) -> None:
    if snapshot.schema_version != BREAKOUT_OUTCOME_SCHEMA_VERSION:
        raise SequentialBreakoutOutcomeError("Cohort schema is unsupported.")
    if snapshot.profile != BREAKOUT_OUTCOME_PROFILE:
        raise SequentialBreakoutOutcomeError("Cohort profile is unsupported.")
    if (
        snapshot.authority != RESEARCH_ONLY
        or snapshot.execution_authority is not False
        or snapshot.conclusions_authorized is not False
    ):
        raise SequentialBreakoutOutcomeError("Cohort attempted to gain authority.")
    if snapshot.cohort_status not in COHORT_STATES:
        raise SequentialBreakoutOutcomeError("Cohort status is unsupported.")
    if (
        snapshot.policy_version != policy.policy_version
        or snapshot.policy_fingerprint != policy.fingerprint
        or snapshot.minimum_prospective_events != policy.minimum_prospective_events
    ):
        raise SequentialBreakoutOutcomeError("Cohort policy identity is invalid.")
    require_sha256(snapshot.cohort_id, "Cohort ID")
    require_sha256(snapshot.fingerprint, "Cohort")
    require_sha256(snapshot.source_ledger_fingerprint, "Source ledger")
    aware_datetime(snapshot.created_at)
    if snapshot.source_event_count != (
        snapshot.eligible_anchor_event_count + snapshot.ineligible_source_event_count
    ):
        raise SequentialBreakoutOutcomeError("Cohort event denominator is invalid.")
    if snapshot.eligible_anchor_event_count != (
        snapshot.prospective_anchor_event_count + snapshot.historical_anchor_event_count
    ):
        raise SequentialBreakoutOutcomeError("Cohort mode denominator is invalid.")
    expected_status = COHORT_THRESHOLD_UNSET
    if policy.minimum_prospective_events is not None:
        prospective_summaries = tuple(
            summary
            for summary in snapshot.summaries
            if summary.observation_mode == PROSPECTIVE
        )
        terminal_coverage = all(
            summary.pending_count == 0 and summary.missing_outcome_count == 0
            for summary in prospective_summaries
        )
        expected_status = (
            COHORT_READY_FOR_LATER_ADJUDICATION
            if snapshot.prospective_anchor_event_count
            >= policy.minimum_prospective_events
            and terminal_coverage
            else COHORT_INSUFFICIENT
        )
    if snapshot.cohort_status != expected_status:
        raise SequentialBreakoutOutcomeError("Cohort readiness is invalid.")
    expected_summary_keys = {
        (mode, horizon)
        for mode in OBSERVATION_MODES
        for horizon in policy.horizons_minutes
    }
    actual_summary_keys = {
        (summary.observation_mode, summary.horizon_minutes)
        for summary in snapshot.summaries
    }
    if actual_summary_keys != expected_summary_keys:
        raise SequentialBreakoutOutcomeError("Cohort summaries are incomplete.")
    for summary in snapshot.summaries:
        validate_horizon_summary(summary)
        expected_events = (
            snapshot.prospective_anchor_event_count
            if summary.observation_mode == PROSPECTIVE
            else snapshot.historical_anchor_event_count
        )
        if summary.eligible_event_count != expected_events:
            raise SequentialBreakoutOutcomeError(
                "Cohort summary event denominator is invalid."
            )
    if tuple(snapshot.latest_outcome_fingerprints) != tuple(
        sorted(snapshot.latest_outcome_fingerprints)
    ):
        raise SequentialBreakoutOutcomeError(
            "Cohort outcome fingerprints are noncanonical."
        )
    for fingerprint in snapshot.latest_outcome_fingerprints:
        require_sha256(fingerprint, "Cohort outcome")
    if snapshot.cohort_id != expected_cohort_id(snapshot):
        raise SequentialBreakoutOutcomeError("Cohort ID is invalid.")
    if snapshot.fingerprint != cohort_fingerprint(snapshot):
        raise SequentialBreakoutOutcomeError("Cohort fingerprint is invalid.")


def validate_horizon_summary(summary: BreakoutCohortHorizonSummary) -> None:
    counts = (
        summary.complete_count,
        summary.pending_count,
        summary.gap_count,
        summary.session_unavailable_count,
        summary.missing_outcome_count,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (
            summary.eligible_event_count,
            summary.positive_return_count,
            summary.failed_below_trigger_count,
        )
        + counts
    ):
        raise SequentialBreakoutOutcomeError(
            "Cohort summary counts must be nonnegative integers."
        )
    if sum(counts) != summary.eligible_event_count:
        raise SequentialBreakoutOutcomeError(
            "Cohort summary outcome denominator is invalid."
        )
    if (
        summary.positive_return_count > summary.complete_count
        or summary.failed_below_trigger_count > summary.complete_count
    ):
        raise SequentialBreakoutOutcomeError(
            "Cohort summary result counts exceed completed evidence."
        )
    metrics = (
        summary.mean_forward_return_pct,
        summary.median_forward_return_pct,
        summary.positive_return_rate_pct,
        summary.failed_below_trigger_rate_pct,
    )
    if summary.complete_count == 0:
        if any(value is not None for value in metrics):
            raise SequentialBreakoutOutcomeError(
                "Empty cohort summary fabricated descriptive metrics."
            )
    else:
        if any(value is None for value in metrics):
            raise SequentialBreakoutOutcomeError(
                "Completed cohort summary is missing descriptive metrics."
            )
        for value in metrics:
            require_finite(value, "Cohort summary metric")
        expected_positive_rate = rounded(
            summary.positive_return_count * 100.0 / summary.complete_count
        )
        expected_failure_rate = rounded(
            summary.failed_below_trigger_count * 100.0 / summary.complete_count
        )
        if (
            summary.positive_return_rate_pct != expected_positive_rate
            or summary.failed_below_trigger_rate_pct != expected_failure_rate
        ):
            raise SequentialBreakoutOutcomeError(
                "Cohort summary rates contradict their result counts."
            )


def latest_outcomes(
    outcomes: Sequence[SequentialBreakoutOutcome],
) -> dict[str, SequentialBreakoutOutcome]:
    latest: dict[str, SequentialBreakoutOutcome] = {}
    for outcome in outcomes:
        current = latest.get(outcome.outcome_key)
        if current is None or outcome.revision > current.revision:
            latest[outcome.outcome_key] = outcome
        elif outcome.revision == current.revision and outcome != current:
            raise SequentialBreakoutOutcomeError(
                "Outcome key has conflicting latest revisions."
            )
    return latest


def source_breakout_ledger_fingerprint(ledger: SequentialBreakoutLedger) -> str:
    validate_source_ledger(ledger)
    return sha256_payload(source_ledger_to_wire(ledger))


def source_event_chain_fingerprint(
    ledger: SequentialBreakoutLedger,
    event: SequentialBreakoutEvent,
) -> str:
    """Bind one outcome to the immutable event prefix that existed at its anchor."""

    validate_source_ledger(ledger)
    matching = tuple(
        candidate
        for candidate in ledger.events
        if candidate.opportunity_id == event.opportunity_id
        and candidate.event_index <= event.event_index
    )
    if not matching or matching[-1] != event:
        raise SequentialBreakoutOutcomeError(
            "Outcome source event is absent from its canonical event chain."
        )
    return sha256_payload([asdict(candidate) for candidate in matching])


def validate_outcome_against_event(
    outcome: SequentialBreakoutOutcome,
    event: SequentialBreakoutEvent,
    *,
    source_event_chain_fingerprint: str,
) -> None:
    expected = {
        "source_event_id": event.event_id,
        "source_event_fingerprint": event.fingerprint,
        "source_breakout_policy_fingerprint": event.policy_fingerprint,
        "opportunity_id": event.opportunity_id,
        "setup_id": event.setup_id,
        "setup_family": event.setup_family,
        "event_type": event.event_type,
        "symbol": event.symbol,
        "session_date": event.session_date,
        "observation_mode": event.observation_mode,
        "event_provider_timestamp": event.provider_timestamp,
        "event_receipt_timestamp": event.receipt_timestamp,
        "anchor_price": event.observed_price,
        "trigger_price": event.trigger_price,
        "event_relative_volume": event.relative_volume,
        "source_event_chain_fingerprint": source_event_chain_fingerprint,
    }
    for field_name, expected_value in expected.items():
        if getattr(outcome, field_name) != expected_value:
            raise SequentialBreakoutOutcomeError(
                f"Outcome {field_name} contradicts the source event."
            )


def outcome_policy_fingerprint(policy: SequentialBreakoutOutcomePolicy) -> str:
    return sha256_payload(asdict(policy))


def expected_outcome_key(
    event: SequentialBreakoutEvent,
    horizon_minutes: int,
    policy: SequentialBreakoutOutcomePolicy,
) -> str:
    return sha256_payload(
        {
            "source_event_id": event.event_id,
            "source_event_fingerprint": event.fingerprint,
            "source_breakout_policy_fingerprint": event.policy_fingerprint,
            "horizon_minutes": horizon_minutes,
            "outcome_policy_fingerprint": policy.fingerprint,
        }
    )


def expected_outcome_key_from_record(
    outcome: SequentialBreakoutOutcome,
    policy: SequentialBreakoutOutcomePolicy,
) -> str:
    return sha256_payload(
        {
            "source_event_id": outcome.source_event_id,
            "source_event_fingerprint": outcome.source_event_fingerprint,
            "source_breakout_policy_fingerprint": outcome.source_breakout_policy_fingerprint,
            "horizon_minutes": outcome.horizon_minutes,
            "outcome_policy_fingerprint": policy.fingerprint,
        }
    )


def material_outcome_payload(outcome: SequentialBreakoutOutcome) -> dict[str, object]:
    payload = asdict(outcome)
    for key in (
        "outcome_id",
        "fingerprint",
        "revision",
        "previous_outcome_id",
        "corrected",
        "first_observed_at",
    ):
        payload.pop(key)
    return payload


def expected_outcome_id(outcome: SequentialBreakoutOutcome) -> str:
    return sha256_payload(
        {
            "outcome_key": outcome.outcome_key,
            "revision": outcome.revision,
            "previous_outcome_id": outcome.previous_outcome_id,
            "material": material_outcome_payload(outcome),
        }
    )


def outcome_fingerprint(outcome: SequentialBreakoutOutcome) -> str:
    return sha256_payload(asdict(replace(outcome, fingerprint="")))


def cohort_fingerprint(snapshot: SequentialBreakoutCohortSnapshot) -> str:
    return sha256_payload(asdict(replace(snapshot, fingerprint="")))


def expected_cohort_id(snapshot: SequentialBreakoutCohortSnapshot) -> str:
    return sha256_payload(
        asdict(replace(snapshot, cohort_id="", fingerprint=""))
    )


def outcome_sort_key(outcome: SequentialBreakoutOutcome) -> tuple[str, int, int]:
    return (outcome.source_event_id, outcome.horizon_minutes, outcome.revision)


def outcome_ledger_to_wire(
    ledger: SequentialBreakoutOutcomeLedger,
) -> dict[str, object]:
    validate_outcome_ledger(ledger)
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "policy": asdict(ledger.policy),
        "outcomes": [asdict(outcome) for outcome in ledger.outcomes],
    }


def outcome_ledger_from_wire(payload: object) -> SequentialBreakoutOutcomeLedger:
    if not isinstance(payload, dict):
        raise SequentialBreakoutOutcomeError("Outcome ledger must be an object.")
    try:
        raw_policy = dict(payload["policy"])
        raw_policy["horizons_minutes"] = tuple(raw_policy["horizons_minutes"])
        policy = SequentialBreakoutOutcomePolicy(**raw_policy)
        outcomes = tuple(
            SequentialBreakoutOutcome(
                **{
                    **dict(item),
                    "source_bar_timestamps": tuple(item["source_bar_timestamps"]),
                    "source_bar_fingerprints": tuple(
                        item["source_bar_fingerprints"]
                    ),
                    "source_set": tuple(item["source_set"]),
                }
            )
            for item in payload["outcomes"]
        )
        ledger = SequentialBreakoutOutcomeLedger(
            policy=policy,
            outcomes=outcomes,
            schema_version=payload["schema_version"],
            profile=payload["profile"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SequentialBreakoutOutcomeError(
            "Outcome ledger shape is invalid."
        ) from exc
    validate_outcome_ledger(ledger)
    return ledger


def aware_text(value: datetime | str, label: str) -> str:
    parsed = value if isinstance(value, datetime) else aware_datetime(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SequentialBreakoutOutcomeError(f"{label} requires a UTC offset.")
    return parsed.isoformat()


def parsed_clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise SequentialBreakoutOutcomeError(
            "Outcome policy session end time is invalid."
        ) from exc
    if parsed.second or parsed.microsecond:
        raise SequentialBreakoutOutcomeError(
            "Outcome policy session end must be minute-aligned."
        )
    return parsed


def percent_change(value: float, anchor: float) -> float:
    return (value / anchor - 1.0) * 100.0


def rounded(value: float | int | None, *, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def require_positive(value: object, label: str) -> float:
    number = require_finite(value, label)
    if number <= 0:
        raise SequentialBreakoutOutcomeError(f"{label} must be positive.")
    return number


def require_finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SequentialBreakoutOutcomeError(f"{label} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise SequentialBreakoutOutcomeError(f"{label} must be finite.")
    return number


def require_sha256(value: object, label: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256_PATTERN.fullmatch(text):
        raise SequentialBreakoutOutcomeError(f"{label} fingerprint is invalid.")
    return text


def require_text(value: object, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise SequentialBreakoutOutcomeError(f"{label} is required.")
    return text
