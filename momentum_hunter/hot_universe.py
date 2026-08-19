"""Deterministic, bounded, provider-neutral hot-universe state.

This module consumes immutable ``DiscoverySnapshot`` observations.  It has no
provider, candle, setup-production, broker, scheduler, runtime, or UI
capability.  A scanner omission is recorded as a bounded-source observation;
it never silently deletes an existing member.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.broad_discovery import (
    COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
    COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY,
    ROW_DISPOSITION_QUALIFIED,
    ROW_DISPOSITION_REJECTED_FILTER,
    SNAPSHOT_STATUS_COMPLETE,
    DiscoveryRow,
    DiscoverySnapshot,
)
from momentum_hunter.path_transaction import PathTransactionLease
from momentum_hunter.time_utils import CENTRAL_TZ


HOT_UNIVERSE_SCHEMA_VERSION = 1
HOT_UNIVERSE_POLICY_VERSION = "hot-universe-policy-v1"
HOT_UNIVERSE_MEMBER_CONTRACT_VERSION = 1
HOT_UNIVERSE_TRANSITION_CONTRACT_VERSION = 1
HOT_UNIVERSE_PROFILE = "persistent-hot-universe-v1"

TRACKED = "TRACKED"
EXPIRED_STATE = "EXPIRED"
MEMBER_STATES = frozenset({TRACKED, EXPIRED_STATE})

PROTECTED = "PROTECTED"
HOT = "HOT"
WARM = "WARM"
PROVIDER_BOUND = "PROVIDER_BOUND"
EXPIRED = "EXPIRED"
TIERS = frozenset({PROTECTED, HOT, WARM, PROVIDER_BOUND, EXPIRED})

ADMITTED = "ADMITTED"
OBSERVED_QUALIFIED = "OBSERVED_QUALIFIED"
OBSERVED_REJECTED = "OBSERVED_REJECTED"
SOURCE_ABSENT = "SOURCE_ABSENT"
PROMOTED = "PROMOTED"
DEMOTED = "DEMOTED"
CAPACITY_BOUND = "CAPACITY_BOUND"
CAPACITY_RESTORED = "CAPACITY_RESTORED"
PROTECTED_TRANSITION = "PROTECTED"
PROTECTION_RELEASED = "PROTECTION_RELEASED"
EXPIRED_TRANSITION = "EXPIRED"
READMITTED_NEW_GENERATION = "READMITTED_NEW_GENERATION"
DISCOVERY_FAILURE = "DISCOVERY_FAILURE"
TRANSITION_TYPES = frozenset(
    {
        ADMITTED,
        OBSERVED_QUALIFIED,
        OBSERVED_REJECTED,
        SOURCE_ABSENT,
        PROMOTED,
        DEMOTED,
        CAPACITY_BOUND,
        CAPACITY_RESTORED,
        PROTECTED_TRANSITION,
        PROTECTION_RELEASED,
        EXPIRED_TRANSITION,
        READMITTED_NEW_GENERATION,
        DISCOVERY_FAILURE,
    }
)

APPLIED = "APPLIED"
DUPLICATE = "DUPLICATE"
FAILURE_RECORDED = "FAILURE_RECORDED"

PROTECTED_COUNTS_AGAINST_HOT_CAPACITY = "COUNTS_AGAINST_HOT_CAPACITY"
PROTECTED_EXEMPT_FROM_HOT_CAPACITY = "EXEMPT_FROM_HOT_CAPACITY"
PROTECTED_CAPACITY_POLICIES = frozenset(
    {
        PROTECTED_COUNTS_AGAINST_HOT_CAPACITY,
        PROTECTED_EXEMPT_FROM_HOT_CAPACITY,
    }
)
EXPIRE_ALL_AT_SESSION_BOUNDARY = "EXPIRE_ALL_AT_SESSION_BOUNDARY"
SESSION_BOUNDARY_POLICIES = frozenset({EXPIRE_ALL_AT_SESSION_BOUNDARY})
REPLAY_FROM_WRITE_ONCE_STATE = "REPLAY_FROM_WRITE_ONCE_STATE"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")


class HotUniverseError(ValueError):
    """Raised when universe evidence is incomplete, contradictory, or unsafe."""


@dataclass(frozen=True)
class HotUniversePolicy:
    """Versioned reference policy; all material fields participate in its hash."""

    policy_version: str = HOT_UNIVERSE_POLICY_VERSION
    maximum_tracked_symbols: int = 30
    maximum_hot_symbols: int = 10
    maximum_warm_symbols: int = 20
    protected_capacity_policy: str = PROTECTED_COUNTS_AGAINST_HOT_CAPACITY
    maximum_consecutive_absent_observations: int = 2
    maximum_consecutive_rejected_observations: int = 2
    fairness_promotion_after_provider_bound_observations: int = 3
    capacity_priority_rules: tuple[str, ...] = (
        "PROTECTED_RESOURCE",
        "ACTIVE_SETUP_REFERENCE",
        "CURRENT_QUALIFICATION",
        "CANONICAL_DISCOVERY_RANK",
        "PROVIDER_BOUND_FAIRNESS",
        "MEMBER_ID",
    )
    eviction_rules: tuple[str, ...] = (
        "EXPLICIT_EXPIRY_ONLY",
        "NO_SILENT_CAPACITY_DELETION",
    )
    fairness_rules: tuple[str, ...] = (
        "DETERMINISTIC_PROVIDER_BOUND_AGING",
        "NO_RANDOM_ALLOCATION",
    )
    session_boundary_rule: str = EXPIRE_ALL_AT_SESSION_BOUNDARY
    restart_rule: str = REPLAY_FROM_WRITE_ONCE_STATE
    schema_version: int = HOT_UNIVERSE_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


@dataclass(frozen=True)
class ProtectedResourceInput:
    """Synthetic caller-supplied resource protection; never broker-derived here."""

    symbol: str
    reason: str


@dataclass(frozen=True)
class SetupReferenceInput:
    """Caller-supplied setup references; this owner never creates setups."""

    symbol: str
    setup_id: str
    terminal: bool


@dataclass(frozen=True)
class DiscoveryFailureObservation:
    """A failed pulse is evidence, not a fictitious complete snapshot."""

    failure_id: str
    source: str
    observed_at: str
    session_date: str
    reason: str
    source_contract_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class HotUniverseMember:
    member_id: str
    symbol: str
    session_date: str
    membership_generation: int
    first_observed_at: str
    last_observed_at: str
    first_discovery_snapshot_id: str
    latest_discovery_snapshot_id: str
    first_candidate_identity: str
    latest_candidate_identity: str
    latest_source_row_id: str
    admission_reason: str
    current_tier: str
    current_state: str
    source_observation_count: int
    consecutive_absent_observations: int
    consecutive_rejected_observations: int
    last_qualified_at: str
    last_rejected_at: str
    last_source_seen_at: str
    active_setup_ids: tuple[str, ...]
    terminal_setup_count: int
    protected_reason: str
    priority_inputs: tuple[tuple[str, str], ...]
    capacity_disposition: str
    provider_bound_since: str
    provider_bound_observation_count: int
    expires_at: str
    predecessor_fingerprint: str
    schema_version: int = HOT_UNIVERSE_MEMBER_CONTRACT_VERSION
    profile: str = HOT_UNIVERSE_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class HotUniverseTransition:
    sequence: int
    transition_id: str
    transition_type: str
    member_id: str
    symbol: str
    session_date: str
    previous_state: str
    next_state: str
    previous_tier: str
    next_tier: str
    reason: str
    source_snapshot_id: str
    source_snapshot_fingerprint: str
    source_row_id: str
    source_row_fingerprint: str
    source_status: str
    source_scope: str
    source_observed_at: str
    snapshot_evaluated_at: str
    recorded_at: str
    policy_version: str
    policy_fingerprint: str
    predecessor_fingerprint: str
    schema_version: int = HOT_UNIVERSE_TRANSITION_CONTRACT_VERSION
    profile: str = HOT_UNIVERSE_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class SnapshotReceipt:
    snapshot_id: str
    snapshot_fingerprint: str
    evaluated_at: str
    session_date: str


@dataclass(frozen=True)
class FailureReceipt:
    failure_id: str
    failure_fingerprint: str
    observed_at: str
    session_date: str


@dataclass(frozen=True)
class HotUniverseState:
    policy_version: str
    policy_fingerprint: str
    current_session_date: str
    members: tuple[HotUniverseMember, ...] = field(default_factory=tuple)
    transitions: tuple[HotUniverseTransition, ...] = field(default_factory=tuple)
    snapshot_receipts: tuple[SnapshotReceipt, ...] = field(default_factory=tuple)
    failure_receipts: tuple[FailureReceipt, ...] = field(default_factory=tuple)
    schema_version: int = HOT_UNIVERSE_SCHEMA_VERSION
    profile: str = HOT_UNIVERSE_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class HotUniverseSummary:
    total_members: int
    protected: int
    hot: int
    warm: int
    provider_bound: int
    expired_this_session: int
    admitted_this_pulse: int
    rediscovered_this_pulse: int
    rejected_observations_this_pulse: int
    source_absent_observations_this_pulse: int
    discovery_failures_this_pulse: int
    promotions_this_pulse: int
    demotions_this_pulse: int
    expirations_this_pulse: int


@dataclass(frozen=True)
class HotUniverseResult:
    status: str
    state: HotUniverseState
    transitions: tuple[HotUniverseTransition, ...]
    summary: HotUniverseSummary


def reference_hot_universe_policy() -> HotUniversePolicy:
    """Return the deterministic v1 proof policy, not a strategy recommendation."""

    return HotUniversePolicy()


def empty_hot_universe_state() -> HotUniverseState:
    return _finalize_state(
        HotUniverseState(
            policy_version="",
            policy_fingerprint="",
            current_session_date="",
        )
    )


def build_discovery_failure_observation(
    *,
    source: str,
    observed_at: datetime,
    session_date: str,
    reason: str,
    source_contract_fingerprint: str,
) -> DiscoveryFailureObservation:
    observed = _timestamp(observed_at, "Discovery failure observed timestamp")
    normalized_session = _session_date(session_date)
    normalized_source = _text(source, "Discovery failure source").lower()
    normalized_reason = _text(reason, "Discovery failure reason")
    _sha256(source_contract_fingerprint, "Discovery failure source contract")
    payload = {
        "source": normalized_source,
        "observedAt": observed,
        "sessionDate": normalized_session,
        "reason": normalized_reason,
        "sourceContractFingerprint": source_contract_fingerprint,
    }
    fingerprint = _fingerprint(payload)
    return DiscoveryFailureObservation(
        failure_id=f"discovery-failure-{fingerprint[:24]}",
        source=normalized_source,
        observed_at=observed,
        session_date=normalized_session,
        reason=normalized_reason,
        source_contract_fingerprint=source_contract_fingerprint,
        fingerprint=fingerprint,
    )


def apply_discovery_snapshot(
    state: HotUniverseState | None,
    *,
    policy: HotUniversePolicy,
    snapshot: DiscoverySnapshot,
    protected_inputs: Iterable[ProtectedResourceInput] = (),
    setup_inputs: Iterable[SetupReferenceInput] = (),
    recorded_at: datetime | None = None,
) -> HotUniverseResult:
    """Apply one complete bounded snapshot as one all-or-nothing observation."""

    _validate_policy(policy)
    validated_snapshot = _validated_snapshot(snapshot)
    event_time = _timestamp(validated_snapshot.evaluated_at, "Snapshot evaluated timestamp")
    recorded = _timestamp(recorded_at or validated_snapshot.evaluated_at, "Transition recorded timestamp")
    if _parse_timestamp(event_time) > _parse_timestamp(recorded):
        raise HotUniverseError("Discovery snapshot cannot be future-dated at processing time.")
    protected_by_symbol = _protected_map(protected_inputs)
    setups_by_symbol = _setup_map(setup_inputs)
    current = _bound_state(state or empty_hot_universe_state(), policy)

    prior_receipt = _receipt_by_snapshot_id(current, validated_snapshot.snapshot_id)
    if prior_receipt is not None:
        if prior_receipt.snapshot_fingerprint != validated_snapshot.fingerprint:
            raise HotUniverseError("Discovery snapshot identity conflicts with stored evidence.")
        return HotUniverseResult(
            status=DUPLICATE,
            state=current,
            transitions=(),
            summary=_summary(current, ()),
        )
    _validate_snapshot_chronology(current, validated_snapshot)

    rows_by_symbol = _rows_by_symbol(validated_snapshot.rows)
    ranks_by_symbol = _canonical_ranks(validated_snapshot.rows)
    members = list(current.members)
    transitions = list(current.transitions)
    pulse_transitions: list[HotUniverseTransition] = []

    def record_transition(
        transition_type: str,
        *,
        member: HotUniverseMember | None,
        previous_state: str,
        next_state: str,
        previous_tier: str,
        next_tier: str,
        reason: str,
        row: DiscoveryRow | None = None,
    ) -> None:
        transition = _new_transition(
            sequence=len(transitions) + 1,
            transition_type=transition_type,
            member=member,
            symbol=(member.symbol if member is not None else (row.symbol if row else "")),
            session_date=validated_snapshot.session_date,
            previous_state=previous_state,
            next_state=next_state,
            previous_tier=previous_tier,
            next_tier=next_tier,
            reason=reason,
            snapshot=validated_snapshot,
            row=row,
            recorded_at=recorded,
            policy=policy,
            predecessor_fingerprint=(member.predecessor_fingerprint if member else ""),
        )
        transitions.append(transition)
        pulse_transitions.append(transition)

    if current.current_session_date:
        if validated_snapshot.session_date < current.current_session_date:
            raise HotUniverseError("Out-of-order discovery session cannot alter universe state.")
        if validated_snapshot.session_date > current.current_session_date:
            for index, member in enumerate(tuple(members)):
                if member.current_state != TRACKED:
                    continue
                expired = _expire_member(member, event_time)
                members[index] = expired
                record_transition(
                    EXPIRED_TRANSITION,
                    member=expired,
                    previous_state=member.current_state,
                    next_state=expired.current_state,
                    previous_tier=member.current_tier,
                    next_tier=expired.current_tier,
                    reason="SESSION_BOUNDARY_EXPIRED",
                )

    active_by_symbol = {
        member.symbol: member
        for member in members
        if member.current_state == TRACKED
        and member.session_date == validated_snapshot.session_date
    }
    if len(active_by_symbol) != len(
        [
            member
            for member in members
            if member.current_state == TRACKED
            and member.session_date == validated_snapshot.session_date
        ]
    ):
        raise HotUniverseError("State contains duplicate active memberships for one symbol.")

    member_index = {member.member_id: index for index, member in enumerate(members)}
    observed_symbols = set(rows_by_symbol)
    for symbol, member in tuple(active_by_symbol.items()):
        row = rows_by_symbol.get(symbol)
        if row is None:
            updated = _evolve_member(
                member,
                latest_discovery_snapshot_id=validated_snapshot.snapshot_id,
                last_observed_at=event_time,
                consecutive_absent_observations=member.consecutive_absent_observations + 1,
            )
            members[member_index[member.member_id]] = updated
            active_by_symbol[symbol] = updated
            record_transition(
                SOURCE_ABSENT,
                member=updated,
                previous_state=member.current_state,
                next_state=updated.current_state,
                previous_tier=member.current_tier,
                next_tier=updated.current_tier,
                reason="SOURCE_NOT_SEEN_IN_BOUNDED_PROVIDER_RESPONSE",
            )
            if updated.consecutive_absent_observations > policy.maximum_consecutive_absent_observations:
                expired = _expire_member(updated, event_time)
                members[member_index[member.member_id]] = expired
                active_by_symbol.pop(symbol, None)
                record_transition(
                    EXPIRED_TRANSITION,
                    member=expired,
                    previous_state=updated.current_state,
                    next_state=expired.current_state,
                    previous_tier=updated.current_tier,
                    next_tier=expired.current_tier,
                    reason="ABSENCE_RETENTION_EXHAUSTED",
                )
            continue

        updated = _member_from_observed_row(
            member,
            row=row,
            snapshot=validated_snapshot,
            event_time=event_time,
            rank=ranks_by_symbol.get(symbol),
        )
        members[member_index[member.member_id]] = updated
        active_by_symbol[symbol] = updated
        record_transition(
            OBSERVED_QUALIFIED if row.disposition == ROW_DISPOSITION_QUALIFIED else OBSERVED_REJECTED,
            member=updated,
            previous_state=member.current_state,
            next_state=updated.current_state,
            previous_tier=member.current_tier,
            next_tier=updated.current_tier,
            reason=(
                "QUALIFIED_DISCOVERY_ROW"
                if row.disposition == ROW_DISPOSITION_QUALIFIED
                else "REJECTED_FILTER_ROW_RETAINED"
            ),
            row=row,
        )
        if (
            row.disposition == ROW_DISPOSITION_REJECTED_FILTER
            and updated.consecutive_rejected_observations
            > policy.maximum_consecutive_rejected_observations
        ):
            expired = _expire_member(updated, event_time)
            members[member_index[member.member_id]] = expired
            active_by_symbol.pop(symbol, None)
            record_transition(
                EXPIRED_TRANSITION,
                member=expired,
                previous_state=updated.current_state,
                next_state=expired.current_state,
                previous_tier=updated.current_tier,
                next_tier=expired.current_tier,
                reason="REJECTED_RETENTION_EXHAUSTED",
                row=row,
            )

    for symbol, row in rows_by_symbol.items():
        if symbol in active_by_symbol or symbol in {
            member.symbol
            for member in members
            if member.current_state == EXPIRED_STATE
            and member.session_date == validated_snapshot.session_date
        } and row.disposition != ROW_DISPOSITION_QUALIFIED:
            continue
        if row.disposition == ROW_DISPOSITION_REJECTED_FILTER:
            record_transition(
                OBSERVED_REJECTED,
                member=None,
                previous_state="NOT_TRACKED",
                next_state="NOT_TRACKED",
                previous_tier="NOT_TRACKED",
                next_tier="NOT_TRACKED",
                reason="REJECTED_FILTER_ROW_NOT_ADMITTED",
                row=row,
            )
            continue
        generation = _next_generation(members, symbol, validated_snapshot.session_date)
        member = _new_member(
            symbol=symbol,
            session_date=validated_snapshot.session_date,
            generation=generation,
            snapshot=validated_snapshot,
            row=row,
            event_time=event_time,
            rank=ranks_by_symbol[symbol],
        )
        members.append(member)
        member_index[member.member_id] = len(members) - 1
        active_by_symbol[symbol] = member
        record_transition(
            READMITTED_NEW_GENERATION if generation > 1 else ADMITTED,
            member=member,
            previous_state=EXPIRED_STATE if generation > 1 else "NOT_TRACKED",
            next_state=member.current_state,
            previous_tier=EXPIRED if generation > 1 else "NOT_TRACKED",
            next_tier=member.current_tier,
            reason="QUALIFIED_DISCOVERY_ROW_ADMITTED",
            row=row,
        )

    for member in tuple(members):
        if member.current_state != TRACKED or member.session_date != validated_snapshot.session_date:
            continue
        updated = _apply_setup_references(member, setups_by_symbol.get(member.symbol))
        protected = protected_by_symbol.get(member.symbol)
        if protected is not None:
            updated = _evolve_member(updated, protected_reason=protected.reason)
            if member.protected_reason != protected.reason:
                record_transition(
                    PROTECTED_TRANSITION,
                    member=updated,
                    previous_state=member.current_state,
                    next_state=updated.current_state,
                    previous_tier=member.current_tier,
                    next_tier=updated.current_tier,
                    reason=protected.reason,
                )
        elif member.protected_reason:
            updated = _evolve_member(updated, protected_reason="")
            record_transition(
                PROTECTION_RELEASED,
                member=updated,
                previous_state=member.current_state,
                next_state=updated.current_state,
                previous_tier=member.current_tier,
                next_tier=updated.current_tier,
                reason="SYNTHETIC_PROTECTED_RESOURCE_RELEASED",
            )
        members[member_index[member.member_id]] = updated
        active_by_symbol[member.symbol] = updated

    members, capacity_transitions = _assign_capacity(
        members=members,
        snapshot=validated_snapshot,
        policy=policy,
        event_time=event_time,
        recorded_at=recorded,
        ranks_by_symbol=ranks_by_symbol,
        existing_transitions=transitions,
    )
    transitions.extend(capacity_transitions)
    pulse_transitions.extend(capacity_transitions)

    updated_state = HotUniverseState(
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
        current_session_date=validated_snapshot.session_date,
        members=tuple(members),
        transitions=tuple(transitions),
        snapshot_receipts=current.snapshot_receipts
        + (
            SnapshotReceipt(
                snapshot_id=validated_snapshot.snapshot_id,
                snapshot_fingerprint=validated_snapshot.fingerprint,
                evaluated_at=event_time,
                session_date=validated_snapshot.session_date,
            ),
        ),
        failure_receipts=current.failure_receipts,
    )
    updated_state = _finalize_state(updated_state)
    validate_hot_universe_state(updated_state)
    return HotUniverseResult(
        status=APPLIED,
        state=updated_state,
        transitions=tuple(pulse_transitions),
        summary=_summary(updated_state, tuple(pulse_transitions)),
    )


def record_discovery_failure(
    state: HotUniverseState | None,
    *,
    policy: HotUniversePolicy,
    failure: DiscoveryFailureObservation,
    recorded_at: datetime | None = None,
) -> HotUniverseResult:
    """Record a failed discovery pulse without aging or expiring members."""

    _validate_policy(policy)
    _validate_failure(failure)
    current = _bound_state(state or empty_hot_universe_state(), policy)
    existing = next(
        (item for item in current.failure_receipts if item.failure_id == failure.failure_id),
        None,
    )
    if existing is not None:
        if existing.failure_fingerprint != failure.fingerprint:
            raise HotUniverseError("Discovery failure identity conflicts with stored evidence.")
        return HotUniverseResult(DUPLICATE, current, (), _summary(current, ()))
    if current.current_session_date and failure.session_date < current.current_session_date:
        raise HotUniverseError("Out-of-order discovery failure cannot alter universe state.")
    recorded = _timestamp(recorded_at or _parse_timestamp(failure.observed_at), "Failure recorded timestamp")
    if _parse_timestamp(failure.observed_at) > _parse_timestamp(recorded):
        raise HotUniverseError("Discovery failure cannot be future-dated at processing time.")
    transition = _new_transition(
        sequence=len(current.transitions) + 1,
        transition_type=DISCOVERY_FAILURE,
        member=None,
        symbol="",
        session_date=failure.session_date,
        previous_state="UNIVERSE_UNCHANGED",
        next_state="UNIVERSE_UNCHANGED",
        previous_tier="UNIVERSE_UNCHANGED",
        next_tier="UNIVERSE_UNCHANGED",
        reason=failure.reason,
        snapshot=None,
        row=None,
        recorded_at=recorded,
        policy=policy,
        predecessor_fingerprint="",
        source_snapshot_id=failure.failure_id,
        source_snapshot_fingerprint=failure.fingerprint,
        source_observed_at=failure.observed_at,
    )
    updated = _finalize_state(
        HotUniverseState(
            policy_version=policy.policy_version,
            policy_fingerprint=policy.fingerprint,
            current_session_date=current.current_session_date or failure.session_date,
            members=current.members,
            transitions=current.transitions + (transition,),
            snapshot_receipts=current.snapshot_receipts,
            failure_receipts=current.failure_receipts
            + (
                FailureReceipt(
                    failure_id=failure.failure_id,
                    failure_fingerprint=failure.fingerprint,
                    observed_at=failure.observed_at,
                    session_date=failure.session_date,
                ),
            ),
        )
    )
    validate_hot_universe_state(updated)
    return HotUniverseResult(
        FAILURE_RECORDED,
        updated,
        (transition,),
        _summary(updated, (transition,)),
    )


class HotUniverseStore:
    """Caller-rooted atomic persistence prototype for deterministic restart tests."""

    def __init__(self, path: Path, *, allow_persistent: bool = False) -> None:
        self.path = Path(path)
        if (
            any(part.lower() == "programdata" for part in self.path.parts)
            and not allow_persistent
        ):
            raise HotUniverseError("Hot-universe store must not target ProgramData.")
        self._lease = PathTransactionLease(self.path)

    def load(self) -> HotUniverseState:
        with self._lease.transaction():
            return self._load_unlocked()

    def apply_snapshot(
        self,
        *,
        policy: HotUniversePolicy,
        snapshot: DiscoverySnapshot,
        protected_inputs: Iterable[ProtectedResourceInput] = (),
        setup_inputs: Iterable[SetupReferenceInput] = (),
        recorded_at: datetime | None = None,
    ) -> HotUniverseResult:
        with self._lease.transaction():
            result = apply_discovery_snapshot(
                self._load_unlocked(),
                policy=policy,
                snapshot=snapshot,
                protected_inputs=protected_inputs,
                setup_inputs=setup_inputs,
                recorded_at=recorded_at,
            )
            if result.status != DUPLICATE:
                self._save_unlocked(result.state)
            return result

    def record_failure(
        self,
        *,
        policy: HotUniversePolicy,
        failure: DiscoveryFailureObservation,
        recorded_at: datetime | None = None,
    ) -> HotUniverseResult:
        with self._lease.transaction():
            result = record_discovery_failure(
                self._load_unlocked(),
                policy=policy,
                failure=failure,
                recorded_at=recorded_at,
            )
            if result.status != DUPLICATE:
                self._save_unlocked(result.state)
            return result

    def _load_unlocked(self) -> HotUniverseState:
        if not self.path.exists():
            return empty_hot_universe_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HotUniverseError(
                f"Hot-universe state cannot be loaded: {type(exc).__name__}"
            ) from exc
        return hot_universe_state_from_wire(payload)

    def _save_unlocked(self, state: HotUniverseState) -> None:
        content = canonical_json_bytes(hot_universe_state_to_wire(state))
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


def hot_universe_state_to_wire(state: HotUniverseState) -> dict[str, object]:
    validate_hot_universe_state(state)
    return asdict(state)


def hot_universe_state_from_wire(payload: object) -> HotUniverseState:
    mapping = _mapping(payload, "Hot-universe state")
    members = tuple(_member_from_wire(_mapping(item, "Member")) for item in _items(mapping, "members"))
    transitions = tuple(_transition_from_wire(_mapping(item, "Transition")) for item in _items(mapping, "transitions"))
    snapshots = tuple(_snapshot_receipt_from_wire(_mapping(item, "Snapshot receipt")) for item in _items(mapping, "snapshot_receipts"))
    failures = tuple(_failure_receipt_from_wire(_mapping(item, "Failure receipt")) for item in _items(mapping, "failure_receipts"))
    state = HotUniverseState(
        policy_version=str(mapping["policy_version"]),
        policy_fingerprint=str(mapping["policy_fingerprint"]),
        current_session_date=str(mapping["current_session_date"]),
        members=members,
        transitions=transitions,
        snapshot_receipts=snapshots,
        failure_receipts=failures,
        schema_version=int(mapping["schema_version"]),
        profile=str(mapping["profile"]),
        fingerprint=str(mapping["fingerprint"]),
    )
    validate_hot_universe_state(state)
    return state


def validate_hot_universe_state(state: HotUniverseState) -> None:
    if state.schema_version != HOT_UNIVERSE_SCHEMA_VERSION or state.profile != HOT_UNIVERSE_PROFILE:
        raise HotUniverseError("Unsupported hot-universe state contract.")
    if state.current_session_date:
        _session_date(state.current_session_date)
    if state.policy_fingerprint:
        _sha256(state.policy_fingerprint, "Hot-universe policy fingerprint")
    elif state.members or state.transitions or state.snapshot_receipts or state.failure_receipts:
        raise HotUniverseError("Nonempty hot-universe state requires a policy fingerprint.")
    if state.fingerprint != _fingerprint(_without_fingerprint(state)):
        raise HotUniverseError("Hot-universe state fingerprint does not match its content.")
    member_ids: set[str] = set()
    active: set[tuple[str, str]] = set()
    for member in state.members:
        _validate_member(member)
        if member.member_id in member_ids:
            raise HotUniverseError("Duplicate hot-universe member identity.")
        member_ids.add(member.member_id)
        if member.current_state == TRACKED:
            key = (member.symbol, member.session_date)
            if key in active:
                raise HotUniverseError("Duplicate active hot-universe member.")
            active.add(key)
    expected_sequence = 1
    for transition in state.transitions:
        _validate_transition(transition)
        if transition.sequence != expected_sequence:
            raise HotUniverseError("Hot-universe transition sequence is not contiguous.")
        expected_sequence += 1
    snapshot_ids: set[str] = set()
    for receipt in state.snapshot_receipts:
        if receipt.snapshot_id in snapshot_ids:
            raise HotUniverseError("Duplicate discovery snapshot receipt.")
        snapshot_ids.add(receipt.snapshot_id)
        _sha256(receipt.snapshot_fingerprint, "Snapshot receipt fingerprint")
        _parse_timestamp(receipt.evaluated_at)
        _session_date(receipt.session_date)
    failure_ids: set[str] = set()
    for receipt in state.failure_receipts:
        if receipt.failure_id in failure_ids:
            raise HotUniverseError("Duplicate discovery failure receipt.")
        failure_ids.add(receipt.failure_id)
        _sha256(receipt.failure_fingerprint, "Failure receipt fingerprint")
        _parse_timestamp(receipt.observed_at)
        _session_date(receipt.session_date)


def _bound_state(state: HotUniverseState, policy: HotUniversePolicy) -> HotUniverseState:
    validate_hot_universe_state(state)
    if not state.policy_fingerprint:
        return _finalize_state(
            replace(
                state,
                policy_version=policy.policy_version,
                policy_fingerprint=policy.fingerprint,
            )
        )
    if state.policy_fingerprint != policy.fingerprint or state.policy_version != policy.policy_version:
        raise HotUniverseError("Policy drift cannot mutate existing hot-universe state.")
    return state


def _validated_snapshot(snapshot: DiscoverySnapshot) -> DiscoverySnapshot:
    if not isinstance(snapshot, DiscoverySnapshot):
        raise HotUniverseError("Hot-universe processing requires a DiscoverySnapshot.")
    for value in (snapshot.requested_at, snapshot.received_at, snapshot.evaluated_at):
        if value.tzinfo is None:
            raise HotUniverseError("Discovery snapshot timestamps must be timezone-aware.")
    try:
        validated = DiscoverySnapshot.from_dict(snapshot.to_dict())
    except (KeyError, TypeError, ValueError) as exc:
        raise HotUniverseError("Discovery snapshot is malformed or tampered.") from exc
    if validated.status != SNAPSHOT_STATUS_COMPLETE:
        raise HotUniverseError("Only completed discovery snapshots may alter membership.")
    if validated.coverage_scope not in {
        COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
        COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY,
    }:
        raise HotUniverseError("Hot-universe input must name a bounded provider query.")
    if validated.session_date != validated.evaluated_at.astimezone(CENTRAL_TZ).date().isoformat():
        raise HotUniverseError("Discovery snapshot session date is inconsistent with its timestamp.")
    return validated


def _validate_snapshot_chronology(state: HotUniverseState, snapshot: DiscoverySnapshot) -> None:
    if not state.snapshot_receipts:
        return
    latest = max(_parse_timestamp(item.evaluated_at) for item in state.snapshot_receipts)
    if _parse_timestamp(_timestamp(snapshot.evaluated_at, "Snapshot evaluated timestamp")) <= latest:
        raise HotUniverseError("Out-of-order discovery snapshot cannot be silently reordered.")


def _rows_by_symbol(rows: Iterable[DiscoveryRow]) -> dict[str, DiscoveryRow]:
    result: dict[str, DiscoveryRow] = {}
    for row in rows:
        if row.symbol in result:
            raise HotUniverseError("One discovery snapshot represents a symbol more than once.")
        result[row.symbol] = row
    return result


def _canonical_ranks(rows: Iterable[DiscoveryRow]) -> dict[str, int]:
    qualified = [row for row in rows if row.disposition == ROW_DISPOSITION_QUALIFIED]
    ordered = sorted(
        qualified,
        key=lambda row: (
            -row.candidate().score,
            -row.candidate().volume,
            -row.candidate().percent_change,
            row.symbol,
            row.row_id,
        ),
    )
    return {row.symbol: index for index, row in enumerate(ordered, start=1)}


def _new_member(
    *,
    symbol: str,
    session_date: str,
    generation: int,
    snapshot: DiscoverySnapshot,
    row: DiscoveryRow,
    event_time: str,
    rank: int,
) -> HotUniverseMember:
    return _finalize_member(
        HotUniverseMember(
            member_id=expected_member_id(symbol, session_date, generation),
            symbol=symbol,
            session_date=session_date,
            membership_generation=generation,
            first_observed_at=event_time,
            last_observed_at=event_time,
            first_discovery_snapshot_id=snapshot.snapshot_id,
            latest_discovery_snapshot_id=snapshot.snapshot_id,
            first_candidate_identity=row.candidate_identity or "",
            latest_candidate_identity=row.candidate_identity or "",
            latest_source_row_id=row.row_id,
            admission_reason="QUALIFIED_DISCOVERY_ROW",
            current_tier=WARM,
            current_state=TRACKED,
            source_observation_count=1,
            consecutive_absent_observations=0,
            consecutive_rejected_observations=0,
            last_qualified_at=event_time,
            last_rejected_at="",
            last_source_seen_at=event_time,
            active_setup_ids=(),
            terminal_setup_count=0,
            protected_reason="",
            priority_inputs=_priority_inputs(rank=rank, member=None),
            capacity_disposition="PENDING_CAPACITY_ASSIGNMENT",
            provider_bound_since="",
            provider_bound_observation_count=0,
            expires_at="",
            predecessor_fingerprint="",
        )
    )


def _member_from_observed_row(
    member: HotUniverseMember,
    *,
    row: DiscoveryRow,
    snapshot: DiscoverySnapshot,
    event_time: str,
    rank: int | None,
) -> HotUniverseMember:
    changes: dict[str, object] = {
        "last_observed_at": event_time,
        "latest_discovery_snapshot_id": snapshot.snapshot_id,
        "latest_source_row_id": row.row_id,
        "last_source_seen_at": event_time,
        "source_observation_count": member.source_observation_count + 1,
        "consecutive_absent_observations": 0,
    }
    if row.disposition == ROW_DISPOSITION_QUALIFIED:
        changes.update(
            {
                "latest_candidate_identity": row.candidate_identity or "",
                "last_qualified_at": event_time,
                "consecutive_rejected_observations": 0,
                "priority_inputs": _priority_inputs(rank=rank, member=member),
            }
        )
    else:
        changes.update(
            {
                "last_rejected_at": event_time,
                "consecutive_rejected_observations": member.consecutive_rejected_observations + 1,
            }
        )
    return _evolve_member(member, **changes)


def _apply_setup_references(
    member: HotUniverseMember,
    references: tuple[SetupReferenceInput, ...] | None,
) -> HotUniverseMember:
    if references is None:
        return member
    active = tuple(sorted(item.setup_id for item in references if not item.terminal))
    terminal_count = len({item.setup_id for item in references if item.terminal})
    if active == member.active_setup_ids and terminal_count == member.terminal_setup_count:
        return member
    return _evolve_member(
        member,
        active_setup_ids=active,
        terminal_setup_count=terminal_count,
    )


def _expire_member(member: HotUniverseMember, event_time: str) -> HotUniverseMember:
    return _evolve_member(
        member,
        current_state=EXPIRED_STATE,
        current_tier=EXPIRED,
        capacity_disposition="EXPIRED",
        expires_at=event_time,
        protected_reason="",
    )


def _assign_capacity(
    *,
    members: list[HotUniverseMember],
    snapshot: DiscoverySnapshot,
    policy: HotUniversePolicy,
    event_time: str,
    recorded_at: str,
    ranks_by_symbol: Mapping[str, int],
    existing_transitions: list[HotUniverseTransition],
) -> tuple[list[HotUniverseMember], list[HotUniverseTransition]]:
    active = [
        member
        for member in members
        if member.current_state == TRACKED and member.session_date == snapshot.session_date
    ]
    protected = [member for member in active if member.protected_reason]
    if (
        policy.protected_capacity_policy == PROTECTED_COUNTS_AGAINST_HOT_CAPACITY
        and len(protected) > policy.maximum_hot_symbols
    ):
        raise HotUniverseError("Protected members exceed configured scarce hot capacity.")
    available_hot = policy.maximum_hot_symbols
    if policy.protected_capacity_policy == PROTECTED_COUNTS_AGAINST_HOT_CAPACITY:
        available_hot -= len(protected)
    ordinary = [member for member in active if not member.protected_reason]
    ordinary.sort(key=lambda member: _capacity_priority(member, snapshot, policy))
    # Protected resources remain retained ahead of ordinary tracked capacity. A
    # constrained ordinary symbol remains in immutable state as PROVIDER_BOUND.
    tracked_ordinary_capacity = max(policy.maximum_tracked_symbols - len(protected), 0)
    tracked_ordinary_ids = {
        member.member_id for member in ordinary[:tracked_ordinary_capacity]
    }
    hot_ids = {
        member.member_id
        for member in ordinary[: min(available_hot, tracked_ordinary_capacity)]
    }
    qualified_symbols = {
        row.symbol for row in snapshot.rows if row.disposition == ROW_DISPOSITION_QUALIFIED
    }
    warm_candidates = [
        member
        for member in ordinary
        if member.member_id in tracked_ordinary_ids
        and member.member_id not in hot_ids
        and member.symbol not in qualified_symbols
    ]
    warm_candidates.sort(key=lambda member: _capacity_priority(member, snapshot, policy))
    warm_ids = {member.member_id for member in warm_candidates[: policy.maximum_warm_symbols]}
    updated: list[HotUniverseMember] = []
    transitions: list[HotUniverseTransition] = []
    sequence = len(existing_transitions) + 1
    for member in members:
        if member.current_state != TRACKED or member.session_date != snapshot.session_date:
            updated.append(member)
            continue
        if member.protected_reason:
            next_tier, disposition = PROTECTED, "PROTECTED_CAPACITY"
        elif member.member_id in hot_ids:
            next_tier, disposition = HOT, "HOT_CAPACITY"
        elif member.member_id in warm_ids:
            next_tier, disposition = WARM, "WARM_RETENTION"
        else:
            next_tier, disposition = (
                PROVIDER_BOUND,
                (
                    "TRACKING_CAPACITY_BOUND"
                    if member.member_id not in tracked_ordinary_ids
                    else "PROVIDER_BOUND"
                ),
            )
        bound_since = member.provider_bound_since
        bound_count = member.provider_bound_observation_count
        if next_tier == PROVIDER_BOUND:
            bound_since = bound_since or event_time
            bound_count += 1
        else:
            bound_since = ""
            bound_count = 0
        rank = ranks_by_symbol.get(member.symbol)
        next_member = _evolve_member(
            member,
            current_tier=next_tier,
            capacity_disposition=disposition,
            provider_bound_since=bound_since,
            provider_bound_observation_count=bound_count,
            priority_inputs=_priority_inputs(rank=rank, member=member, next_tier=next_tier, provider_bound_count=bound_count),
        )
        updated.append(next_member)
        transition_type = _capacity_transition(member.current_tier, next_tier)
        if transition_type:
            transitions.append(
                _new_transition(
                    sequence=sequence,
                    transition_type=transition_type,
                    member=next_member,
                    symbol=next_member.symbol,
                    session_date=snapshot.session_date,
                    previous_state=member.current_state,
                    next_state=next_member.current_state,
                    previous_tier=member.current_tier,
                    next_tier=next_tier,
                    reason=disposition,
                    snapshot=snapshot,
                    row=next((row for row in snapshot.rows if row.symbol == member.symbol), None),
                    recorded_at=recorded_at,
                    policy=policy,
                    predecessor_fingerprint=member.fingerprint,
                )
            )
            sequence += 1
    return updated, transitions


def _capacity_priority(
    member: HotUniverseMember,
    snapshot: DiscoverySnapshot,
    policy: HotUniversePolicy,
) -> tuple[int, int, int, int, str]:
    current_qualified = int(member.latest_discovery_snapshot_id == snapshot.snapshot_id and member.last_qualified_at == _timestamp(snapshot.evaluated_at, "Snapshot evaluated timestamp"))
    has_active_setup = int(bool(member.active_setup_ids))
    fairness_ready = int(
        member.provider_bound_observation_count
        >= policy.fairness_promotion_after_provider_bound_observations
    )
    rank = _priority_value(member.priority_inputs, "canonicalRank", default=999999)
    return (-fairness_ready, -has_active_setup, -current_qualified, rank, member.member_id)


def _capacity_transition(previous: str, current: str) -> str | None:
    if previous == current:
        return None
    if previous == PROVIDER_BOUND and current == HOT:
        return CAPACITY_RESTORED
    if current == PROVIDER_BOUND:
        return CAPACITY_BOUND
    if previous == HOT and current in {WARM, PROTECTED}:
        return DEMOTED
    if current == HOT:
        return PROMOTED
    if current == PROTECTED:
        return PROTECTED_TRANSITION
    if previous == PROTECTED:
        return PROTECTION_RELEASED
    return DEMOTED if current == WARM else PROMOTED


def _new_transition(
    *,
    sequence: int,
    transition_type: str,
    member: HotUniverseMember | None,
    symbol: str,
    session_date: str,
    previous_state: str,
    next_state: str,
    previous_tier: str,
    next_tier: str,
    reason: str,
    snapshot: DiscoverySnapshot | None,
    row: DiscoveryRow | None,
    recorded_at: str,
    policy: HotUniversePolicy,
    predecessor_fingerprint: str,
    source_snapshot_id: str | None = None,
    source_snapshot_fingerprint: str | None = None,
    source_observed_at: str | None = None,
) -> HotUniverseTransition:
    if transition_type not in TRANSITION_TYPES:
        raise HotUniverseError("Unknown hot-universe transition type.")
    snapshot_id = source_snapshot_id or (snapshot.snapshot_id if snapshot else "")
    snapshot_fingerprint = source_snapshot_fingerprint or (snapshot.fingerprint if snapshot else "")
    observed_at = source_observed_at or (_timestamp(snapshot.received_at, "Snapshot receipt timestamp") if snapshot else recorded_at)
    evaluated_at = _timestamp(snapshot.evaluated_at, "Snapshot evaluated timestamp") if snapshot else observed_at
    transition = HotUniverseTransition(
        sequence=sequence,
        transition_id="",
        transition_type=transition_type,
        member_id=member.member_id if member else "",
        symbol=symbol,
        session_date=session_date,
        previous_state=previous_state,
        next_state=next_state,
        previous_tier=previous_tier,
        next_tier=next_tier,
        reason=reason,
        source_snapshot_id=snapshot_id,
        source_snapshot_fingerprint=snapshot_fingerprint,
        source_row_id=row.row_id if row else "",
        source_row_fingerprint=row.fingerprint if row else "",
        source_status=snapshot.status if snapshot else "DISCOVERY_FAILURE",
        source_scope=snapshot.coverage_scope if snapshot else COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
        source_observed_at=observed_at,
        snapshot_evaluated_at=evaluated_at,
        recorded_at=recorded_at,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
        predecessor_fingerprint=predecessor_fingerprint,
        fingerprint="",
    )
    fingerprint = _fingerprint(_transition_fingerprint_payload(transition))
    return replace(
        transition,
        transition_id=f"hot-transition-{fingerprint[:24]}",
        fingerprint=fingerprint,
    )


def _summary(state: HotUniverseState, pulse: tuple[HotUniverseTransition, ...]) -> HotUniverseSummary:
    active = [member for member in state.members if member.current_state == TRACKED]
    types = [transition.transition_type for transition in pulse]
    return HotUniverseSummary(
        total_members=len(active),
        protected=sum(member.current_tier == PROTECTED for member in active),
        hot=sum(member.current_tier == HOT for member in active),
        warm=sum(member.current_tier == WARM for member in active),
        provider_bound=sum(member.current_tier == PROVIDER_BOUND for member in active),
        expired_this_session=sum(
            member.current_state == EXPIRED_STATE and member.session_date == state.current_session_date
            for member in state.members
        ),
        admitted_this_pulse=sum(item in {ADMITTED, READMITTED_NEW_GENERATION} for item in types),
        rediscovered_this_pulse=types.count(OBSERVED_QUALIFIED),
        rejected_observations_this_pulse=types.count(OBSERVED_REJECTED),
        source_absent_observations_this_pulse=types.count(SOURCE_ABSENT),
        discovery_failures_this_pulse=types.count(DISCOVERY_FAILURE),
        promotions_this_pulse=types.count(PROMOTED) + types.count(CAPACITY_RESTORED),
        demotions_this_pulse=types.count(DEMOTED) + types.count(CAPACITY_BOUND),
        expirations_this_pulse=types.count(EXPIRED_TRANSITION),
    )


def expected_member_id(symbol: str, session_date: str, generation: int) -> str:
    normalized_symbol = _symbol(symbol)
    normalized_session = _session_date(session_date)
    if generation < 1:
        raise HotUniverseError("Membership generation must be positive.")
    return f"hot-member-{normalized_symbol}-{normalized_session}-g{generation}"


def _next_generation(members: Iterable[HotUniverseMember], symbol: str, session_date: str) -> int:
    return 1 + max(
        (member.membership_generation for member in members if member.symbol == symbol and member.session_date == session_date),
        default=0,
    )


def _receipt_by_snapshot_id(state: HotUniverseState, snapshot_id: str) -> SnapshotReceipt | None:
    return next((item for item in state.snapshot_receipts if item.snapshot_id == snapshot_id), None)


def _evolve_member(member: HotUniverseMember, **changes: object) -> HotUniverseMember:
    changes["predecessor_fingerprint"] = member.fingerprint
    changes["fingerprint"] = ""
    return _finalize_member(replace(member, **changes))


def _finalize_member(member: HotUniverseMember) -> HotUniverseMember:
    return replace(member, fingerprint=_fingerprint(_without_fingerprint(member)))


def _finalize_state(state: HotUniverseState) -> HotUniverseState:
    return replace(state, fingerprint=_fingerprint(_without_fingerprint(state)))


def _without_fingerprint(record: object) -> object:
    payload = asdict(record)
    payload.pop("fingerprint", None)
    return payload


def _priority_inputs(
    *,
    rank: int | None,
    member: HotUniverseMember | None,
    next_tier: str = WARM,
    provider_bound_count: int | None = None,
) -> tuple[tuple[str, str], ...]:
    count = provider_bound_count
    if count is None:
        count = member.provider_bound_observation_count if member else 0
    return tuple(
        sorted(
            {
                "activeSetupCount": str(len(member.active_setup_ids) if member else 0),
                "canonicalRank": str(rank if rank is not None else 999999),
                "currentTier": next_tier,
                "protected": str(bool(member and member.protected_reason)).lower(),
                "providerBoundObservationCount": str(count),
            }.items()
        )
    )


def _priority_value(values: tuple[tuple[str, str], ...], key: str, *, default: int) -> int:
    try:
        return int(dict(values).get(key, default))
    except (TypeError, ValueError):
        return default


def _protected_map(inputs: Iterable[ProtectedResourceInput]) -> dict[str, ProtectedResourceInput]:
    result: dict[str, ProtectedResourceInput] = {}
    for item in inputs:
        if not isinstance(item, ProtectedResourceInput):
            raise HotUniverseError("Protected state must use ProtectedResourceInput.")
        symbol = _symbol(item.symbol)
        normalized = ProtectedResourceInput(symbol=symbol, reason=_text(item.reason, "Protected reason"))
        if symbol in result and result[symbol] != normalized:
            raise HotUniverseError("Conflicting protected state for one symbol.")
        result[symbol] = normalized
    return result


def _setup_map(inputs: Iterable[SetupReferenceInput]) -> dict[str, tuple[SetupReferenceInput, ...]]:
    grouped: dict[str, list[SetupReferenceInput]] = {}
    seen: set[tuple[str, str]] = set()
    for item in inputs:
        if not isinstance(item, SetupReferenceInput):
            raise HotUniverseError("Setup references must use SetupReferenceInput.")
        symbol = _symbol(item.symbol)
        setup_id = _text(item.setup_id, "Setup reference identity")
        key = (symbol, setup_id)
        if key in seen:
            raise HotUniverseError("Duplicate setup reference for one member.")
        seen.add(key)
        grouped.setdefault(symbol, []).append(
            SetupReferenceInput(symbol=symbol, setup_id=setup_id, terminal=bool(item.terminal))
        )
    return {symbol: tuple(items) for symbol, items in grouped.items()}


def _validate_policy(policy: HotUniversePolicy) -> None:
    if not isinstance(policy, HotUniversePolicy):
        raise HotUniverseError("Hot-universe policy is required.")
    if policy.schema_version != HOT_UNIVERSE_SCHEMA_VERSION:
        raise HotUniverseError("Unsupported hot-universe policy version.")
    _text(policy.policy_version, "Hot-universe policy version")
    if policy.maximum_tracked_symbols < 1 or policy.maximum_hot_symbols < 1:
        raise HotUniverseError("Tracked and hot capacities must be positive.")
    if policy.maximum_warm_symbols < 0:
        raise HotUniverseError("Warm capacity cannot be negative.")
    if policy.maximum_tracked_symbols < policy.maximum_hot_symbols:
        raise HotUniverseError("Tracked capacity cannot be lower than hot capacity.")
    if min(
        policy.maximum_consecutive_absent_observations,
        policy.maximum_consecutive_rejected_observations,
    ) < 0:
        raise HotUniverseError("Retention observation limits cannot be negative.")
    if policy.fairness_promotion_after_provider_bound_observations < 1:
        raise HotUniverseError("Fairness promotion threshold must be positive.")
    if policy.protected_capacity_policy not in PROTECTED_CAPACITY_POLICIES:
        raise HotUniverseError("Unknown protected capacity policy.")
    if policy.session_boundary_rule not in SESSION_BOUNDARY_POLICIES:
        raise HotUniverseError("Unknown session boundary rule.")
    if policy.restart_rule != REPLAY_FROM_WRITE_ONCE_STATE:
        raise HotUniverseError("Unknown restart rule.")
    if not policy.capacity_priority_rules or not policy.eviction_rules or not policy.fairness_rules:
        raise HotUniverseError("Hot-universe policy requires explicit rule declarations.")


def _validate_member(member: HotUniverseMember) -> None:
    if member.schema_version != HOT_UNIVERSE_MEMBER_CONTRACT_VERSION or member.profile != HOT_UNIVERSE_PROFILE:
        raise HotUniverseError("Unsupported hot-universe member contract.")
    _symbol(member.symbol); _session_date(member.session_date)
    if member.member_id != expected_member_id(member.symbol, member.session_date, member.membership_generation):
        raise HotUniverseError("Hot-universe member identity is inconsistent.")
    if member.current_state not in MEMBER_STATES or member.current_tier not in TIERS:
        raise HotUniverseError("Unknown hot-universe member state or tier.")
    if member.current_state == EXPIRED_STATE and member.current_tier != EXPIRED:
        raise HotUniverseError("Expired member must use the EXPIRED tier.")
    if member.current_state == TRACKED and member.current_tier == EXPIRED:
        raise HotUniverseError("Tracked member cannot use the EXPIRED tier.")
    if min(member.source_observation_count, member.consecutive_absent_observations, member.consecutive_rejected_observations, member.terminal_setup_count, member.provider_bound_observation_count) < 0:
        raise HotUniverseError("Hot-universe member counts cannot be negative.")
    for value in (member.first_observed_at, member.last_observed_at, member.last_source_seen_at):
        _parse_timestamp(value)
    if member.last_qualified_at: _parse_timestamp(member.last_qualified_at)
    if member.last_rejected_at: _parse_timestamp(member.last_rejected_at)
    if member.expires_at: _parse_timestamp(member.expires_at)
    if member.predecessor_fingerprint: _sha256(member.predecessor_fingerprint, "Member predecessor fingerprint")
    if member.fingerprint != _fingerprint(_without_fingerprint(member)):
        raise HotUniverseError("Hot-universe member fingerprint does not match its content.")


def _validate_transition(transition: HotUniverseTransition) -> None:
    if transition.schema_version != HOT_UNIVERSE_TRANSITION_CONTRACT_VERSION or transition.profile != HOT_UNIVERSE_PROFILE:
        raise HotUniverseError("Unsupported hot-universe transition contract.")
    if transition.transition_type not in TRANSITION_TYPES:
        raise HotUniverseError("Unknown hot-universe transition type.")
    if transition.sequence < 1:
        raise HotUniverseError("Hot-universe transition sequence must be positive.")
    _session_date(transition.session_date)
    if transition.member_id:
        _symbol(transition.symbol)
    for value in (transition.source_observed_at, transition.snapshot_evaluated_at, transition.recorded_at):
        _parse_timestamp(value)
    _sha256(transition.source_snapshot_fingerprint, "Transition source fingerprint")
    _sha256(transition.policy_fingerprint, "Transition policy fingerprint")
    if transition.source_row_fingerprint:
        _sha256(transition.source_row_fingerprint, "Transition source row fingerprint")
    if transition.predecessor_fingerprint:
        _sha256(transition.predecessor_fingerprint, "Transition predecessor fingerprint")
    expected = _fingerprint(_transition_fingerprint_payload(transition))
    if transition.fingerprint != expected or transition.transition_id != f"hot-transition-{expected[:24]}":
        raise HotUniverseError("Hot-universe transition fingerprint does not match its content.")


def _transition_fingerprint_payload(transition: HotUniverseTransition) -> dict[str, object]:
    """Use the published transition names, not Python implementation field names."""

    return {
        "sequence": transition.sequence,
        "transitionType": transition.transition_type,
        "memberId": transition.member_id,
        "symbol": transition.symbol,
        "sessionDate": transition.session_date,
        "previousState": transition.previous_state,
        "nextState": transition.next_state,
        "previousTier": transition.previous_tier,
        "nextTier": transition.next_tier,
        "reason": transition.reason,
        "sourceSnapshotId": transition.source_snapshot_id,
        "sourceSnapshotFingerprint": transition.source_snapshot_fingerprint,
        "sourceRowId": transition.source_row_id,
        "sourceRowFingerprint": transition.source_row_fingerprint,
        "sourceStatus": transition.source_status,
        "sourceScope": transition.source_scope,
        "sourceObservedAt": transition.source_observed_at,
        "snapshotEvaluatedAt": transition.snapshot_evaluated_at,
        "recordedAt": transition.recorded_at,
        "policyVersion": transition.policy_version,
        "policyFingerprint": transition.policy_fingerprint,
        "predecessorFingerprint": transition.predecessor_fingerprint,
    }


def _validate_failure(failure: DiscoveryFailureObservation) -> None:
    _text(failure.source, "Discovery failure source")
    _parse_timestamp(failure.observed_at); _session_date(failure.session_date)
    _text(failure.reason, "Discovery failure reason")
    _sha256(failure.source_contract_fingerprint, "Discovery failure source contract")
    payload = {
        "source": failure.source,
        "observedAt": failure.observed_at,
        "sessionDate": failure.session_date,
        "reason": failure.reason,
        "sourceContractFingerprint": failure.source_contract_fingerprint,
    }
    expected = _fingerprint(payload)
    if failure.fingerprint != expected or failure.failure_id != f"discovery-failure-{expected[:24]}":
        raise HotUniverseError("Discovery failure fingerprint does not match its content.")


def _member_from_wire(payload: Mapping[str, object]) -> HotUniverseMember:
    return HotUniverseMember(
        member_id=str(payload["member_id"]), symbol=str(payload["symbol"]), session_date=str(payload["session_date"]), membership_generation=int(payload["membership_generation"]), first_observed_at=str(payload["first_observed_at"]), last_observed_at=str(payload["last_observed_at"]), first_discovery_snapshot_id=str(payload["first_discovery_snapshot_id"]), latest_discovery_snapshot_id=str(payload["latest_discovery_snapshot_id"]), first_candidate_identity=str(payload["first_candidate_identity"]), latest_candidate_identity=str(payload["latest_candidate_identity"]), latest_source_row_id=str(payload["latest_source_row_id"]), admission_reason=str(payload["admission_reason"]), current_tier=str(payload["current_tier"]), current_state=str(payload["current_state"]), source_observation_count=int(payload["source_observation_count"]), consecutive_absent_observations=int(payload["consecutive_absent_observations"]), consecutive_rejected_observations=int(payload["consecutive_rejected_observations"]), last_qualified_at=str(payload["last_qualified_at"]), last_rejected_at=str(payload["last_rejected_at"]), last_source_seen_at=str(payload["last_source_seen_at"]), active_setup_ids=tuple(str(item) for item in _items(payload, "active_setup_ids")), terminal_setup_count=int(payload["terminal_setup_count"]), protected_reason=str(payload["protected_reason"]), priority_inputs=tuple((str(item[0]), str(item[1])) for item in _items(payload, "priority_inputs")), capacity_disposition=str(payload["capacity_disposition"]), provider_bound_since=str(payload["provider_bound_since"]), provider_bound_observation_count=int(payload["provider_bound_observation_count"]), expires_at=str(payload["expires_at"]), predecessor_fingerprint=str(payload["predecessor_fingerprint"]), schema_version=int(payload["schema_version"]), profile=str(payload["profile"]), fingerprint=str(payload["fingerprint"])
    )


def _transition_from_wire(payload: Mapping[str, object]) -> HotUniverseTransition:
    return HotUniverseTransition(**{key: payload[key] for key in HotUniverseTransition.__dataclass_fields__})


def _snapshot_receipt_from_wire(payload: Mapping[str, object]) -> SnapshotReceipt:
    return SnapshotReceipt(**{key: str(payload[key]) for key in SnapshotReceipt.__dataclass_fields__})


def _failure_receipt_from_wire(payload: Mapping[str, object]) -> FailureReceipt:
    return FailureReceipt(**{key: str(payload[key]) for key in FailureReceipt.__dataclass_fields__})


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HotUniverseError(f"{label} must be an object.")
    return value


def _items(mapping: Mapping[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise HotUniverseError(f"Hot-universe wire field {key} must be a list.")
    return value


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _timestamp(value: datetime, label: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HotUniverseError(f"{label} must be timezone-aware.")
    return value.astimezone(CENTRAL_TZ).isoformat()


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HotUniverseError("Timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise HotUniverseError("Timestamp must be timezone-aware.")
    return parsed.astimezone(CENTRAL_TZ)


def _session_date(value: str) -> str:
    try:
        return datetime.fromisoformat(f"{value}T00:00:00").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise HotUniverseError("Session date is invalid.") from exc


def _symbol(value: object) -> str:
    normalized = _text(value, "Symbol").upper()
    if not _SYMBOL.fullmatch(normalized):
        raise HotUniverseError("Symbol is invalid.")
    return normalized


def _text(value: object, label: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise HotUniverseError(f"{label} is required.")
    return normalized


def _sha256(value: str, label: str) -> str:
    if not _SHA256.fullmatch(str(value)):
        raise HotUniverseError(f"{label} must be a SHA-256 fingerprint.")
    return str(value)
