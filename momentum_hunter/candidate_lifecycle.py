"""Provider-neutral candidate lifecycle evidence and event coordination.

This module records already-observed lifecycle facts. It does not discover price
patterns, score candidates, build TradePlans, evaluate risk, or contact a broker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    EASTERN_TZ,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
    SUPPORTED_SETUP_FAMILIES,
)


CANDIDATE_LIFECYCLE_SCHEMA_VERSION = 1
CANDIDATE_LIFECYCLE_PROFILE = "candidate-lifecycle-v1"

DISCOVERED = "DISCOVERED"
WATCHING = "WATCHING"
IMPULSE_DETECTED = "IMPULSE_DETECTED"
BREAKOUT_FORMING = "BREAKOUT_FORMING"
BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
PULLBACK_FORMING = "PULLBACK_FORMING"
RECLAIM_FORMING = "RECLAIM_FORMING"
EXECUTION_ELIGIBLE = "EXECUTION_ELIGIBLE"
ENTRY_MISSED = "ENTRY_MISSED"
EXHAUSTION_RISK = "EXHAUSTION_RISK"
FAILED_BREAKOUT = "FAILED_BREAKOUT"
INVALIDATED = "INVALIDATED"
COOLDOWN = "COOLDOWN"
DATA_STALE = "DATA_STALE"

CANDIDATE_STATES = frozenset(
    {
        DISCOVERED,
        WATCHING,
        IMPULSE_DETECTED,
        BREAKOUT_FORMING,
        BREAKOUT_CONFIRMED,
        PULLBACK_FORMING,
        RECLAIM_FORMING,
        EXECUTION_ELIGIBLE,
        ENTRY_MISSED,
        EXHAUSTION_RISK,
        FAILED_BREAKOUT,
        INVALIDATED,
        COOLDOWN,
        DATA_STALE,
    }
)

SETUP_BOUND_STATES = frozenset(
    {
        BREAKOUT_FORMING,
        BREAKOUT_CONFIRMED,
        PULLBACK_FORMING,
        RECLAIM_FORMING,
        EXECUTION_ELIGIBLE,
        ENTRY_MISSED,
        EXHAUSTION_RISK,
        FAILED_BREAKOUT,
    }
)

LEGAL_TRANSITIONS = {
    DISCOVERED: frozenset({WATCHING, DATA_STALE, INVALIDATED}),
    WATCHING: frozenset(
        {
            IMPULSE_DETECTED,
            BREAKOUT_FORMING,
            PULLBACK_FORMING,
            RECLAIM_FORMING,
            DATA_STALE,
            INVALIDATED,
        }
    ),
    IMPULSE_DETECTED: frozenset(
        {
            BREAKOUT_FORMING,
            PULLBACK_FORMING,
            RECLAIM_FORMING,
            EXHAUSTION_RISK,
            FAILED_BREAKOUT,
            DATA_STALE,
            INVALIDATED,
        }
    ),
    BREAKOUT_FORMING: frozenset(
        {
            BREAKOUT_CONFIRMED,
            ENTRY_MISSED,
            FAILED_BREAKOUT,
            EXHAUSTION_RISK,
            DATA_STALE,
            INVALIDATED,
        }
    ),
    BREAKOUT_CONFIRMED: frozenset(
        {
            EXECUTION_ELIGIBLE,
            PULLBACK_FORMING,
            FAILED_BREAKOUT,
            ENTRY_MISSED,
            DATA_STALE,
            INVALIDATED,
        }
    ),
    PULLBACK_FORMING: frozenset(
        {
            RECLAIM_FORMING,
            EXECUTION_ELIGIBLE,
            ENTRY_MISSED,
            DATA_STALE,
            INVALIDATED,
        }
    ),
    RECLAIM_FORMING: frozenset(
        {EXECUTION_ELIGIBLE, ENTRY_MISSED, DATA_STALE, INVALIDATED}
    ),
    EXECUTION_ELIGIBLE: frozenset(
        {ENTRY_MISSED, INVALIDATED, COOLDOWN, DATA_STALE}
    ),
    ENTRY_MISSED: frozenset({COOLDOWN, PULLBACK_FORMING, INVALIDATED, DATA_STALE}),
    EXHAUSTION_RISK: frozenset(
        {COOLDOWN, PULLBACK_FORMING, INVALIDATED, WATCHING, DATA_STALE}
    ),
    FAILED_BREAKOUT: frozenset(
        {COOLDOWN, RECLAIM_FORMING, INVALIDATED, DATA_STALE}
    ),
    INVALIDATED: frozenset({COOLDOWN}),
    COOLDOWN: frozenset({WATCHING, DATA_STALE, INVALIDATED}),
    DATA_STALE: frozenset({INVALIDATED}),
}

DISCOVERY_EVENT = "DISCOVERY"
STATE_TRANSITION_EVENT = "STATE_TRANSITION"
EVIDENCE_REFRESH_EVENT = "EVIDENCE_REFRESH"
DATA_STALE_EVENT = "DATA_STALE"
DATA_RECOVERED_EVENT = "DATA_RECOVERED"
EVENT_TYPES = frozenset(
    {
        DISCOVERY_EVENT,
        STATE_TRANSITION_EVENT,
        EVIDENCE_REFRESH_EVENT,
        DATA_STALE_EVENT,
        DATA_RECOVERED_EVENT,
    }
)

DISCOVERY_MEMBERSHIP_CHANGED = "DISCOVERY_MEMBERSHIP_CHANGED"
MONITORING_ACTIVATED = "MONITORING_ACTIVATED"
SETUP_IDENTITY_CHANGED = "SETUP_IDENTITY_CHANGED"
SETUP_STATE_CHANGED = "SETUP_STATE_CHANGED"
EVIDENCE_AUTHORITY_CHANGED = "EVIDENCE_AUTHORITY_CHANGED"
DATA_BECAME_STALE = "DATA_BECAME_STALE"
DATA_RECOVERED_DELTA = "DATA_RECOVERED"
COOLDOWN_BOUNDARY = "COOLDOWN_BOUNDARY"
INVALIDATION_BOUNDARY = "INVALIDATION_BOUNDARY"
MATERIAL_DELTA_KINDS = frozenset(
    {
        DISCOVERY_MEMBERSHIP_CHANGED,
        MONITORING_ACTIVATED,
        SETUP_IDENTITY_CHANGED,
        SETUP_STATE_CHANGED,
        EVIDENCE_AUTHORITY_CHANGED,
        DATA_BECAME_STALE,
        DATA_RECOVERED_DELTA,
        COOLDOWN_BOUNDARY,
        INVALIDATION_BOUNDARY,
    }
)

DISCOVERY_SCOPE = "DISCOVERY"
MONITORING_SCOPE = "MONITORING"
AVAILABILITY_SCOPES = frozenset({DISCOVERY_SCOPE, MONITORING_SCOPE})
AVAILABILITY_FAILED = "FAILED"
AVAILABILITY_MISSED = "MISSED"
AVAILABILITY_RECOVERED = "RECOVERED"
AVAILABILITY_STATUSES = frozenset(
    {AVAILABILITY_FAILED, AVAILABILITY_MISSED, AVAILABILITY_RECOVERED}
)

CREATED = "CREATED"
DUPLICATE = "DUPLICATE"
NO_CHANGE = "NO_CHANGE"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")


class CandidateLifecycleError(ValueError):
    """Raised when lifecycle evidence is invalid or contradictory."""


@dataclass(frozen=True)
class CandidateLifecyclePolicy:
    policy_version: str
    cooldown_seconds: int
    hysteresis_profile: str
    minimum_delta_profile: str
    quote_only_events_create_cycles: bool = False

    @property
    def fingerprint(self) -> str:
        return candidate_lifecycle_policy_fingerprint(self)


@dataclass(frozen=True)
class CandidateLifecycleEvent:
    sequence: int
    event_id: str
    opportunity_id: str
    symbol: str
    session_date: str
    originating_evidence_family: str
    event_type: str
    previous_state: str
    next_state: str
    occurred_at: str
    provider_timestamp: str
    receipt_timestamp: str
    source_identity: str
    evidence_fingerprint: str
    material_delta_kind: str
    reason: str
    policy_version: str
    policy_fingerprint: str
    cooldown_seconds: int
    hysteresis_profile: str
    minimum_delta_profile: str
    quote_only_events_create_cycles: bool
    setup_id: str = ""
    setup_family: str = ""
    setup_sequence: int = 0
    predecessor_setup_id: str = ""
    previous_event_id: str = ""
    schema_version: int = CANDIDATE_LIFECYCLE_SCHEMA_VERSION
    profile: str = CANDIDATE_LIFECYCLE_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeAvailabilityEvent:
    sequence: int
    event_id: str
    scope: str
    status: str
    occurred_at: str
    source_identity: str
    evidence_fingerprint: str
    reason: str
    policy_version: str
    policy_fingerprint: str
    cooldown_seconds: int
    hysteresis_profile: str
    minimum_delta_profile: str
    quote_only_events_create_cycles: bool
    schema_version: int = CANDIDATE_LIFECYCLE_SCHEMA_VERSION
    profile: str = CANDIDATE_LIFECYCLE_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class CandidateLifecycleSnapshot:
    opportunity_id: str
    symbol: str
    session_date: str
    originating_evidence_family: str
    current_state: str
    last_non_stale_state: str
    latest_event_id: str
    latest_evidence_fingerprint: str
    current_setup_id: str = ""
    current_setup_family: str = ""
    current_setup_sequence: int = 0
    latest_policy_fingerprint: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class CandidateLifecycleLedger:
    events: tuple[CandidateLifecycleEvent, ...] = field(default_factory=tuple)
    availability_events: tuple[RuntimeAvailabilityEvent, ...] = field(
        default_factory=tuple
    )
    schema_version: int = CANDIDATE_LIFECYCLE_SCHEMA_VERSION
    profile: str = CANDIDATE_LIFECYCLE_PROFILE


@dataclass(frozen=True)
class CandidateLifecycleResult:
    status: str
    event: CandidateLifecycleEvent | None
    snapshot: CandidateLifecycleSnapshot | None


class CandidateLifecycleStore:
    """Atomic append-only JSON store with deterministic replay validation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> CandidateLifecycleLedger:
        with self._lock:
            if not self.path.exists():
                return CandidateLifecycleLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CandidateLifecycleError(
                    f"Candidate lifecycle evidence cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def append_event(self, event: CandidateLifecycleEvent) -> CandidateLifecycleEvent:
        with self._lock:
            ledger = self.load()
            existing = next(
                (item for item in ledger.events if item.event_id == event.event_id),
                None,
            )
            if existing is not None:
                if existing == event:
                    return existing
                raise CandidateLifecycleError(
                    "Candidate lifecycle event identity conflicts with stored evidence."
                )
            updated = replace(ledger, events=ledger.events + (event,))
            validate_ledger(updated)
            self._save(updated)
            return event

    def append_availability_event(
        self, event: RuntimeAvailabilityEvent
    ) -> RuntimeAvailabilityEvent:
        with self._lock:
            ledger = self.load()
            existing = next(
                (
                    item
                    for item in ledger.availability_events
                    if item.event_id == event.event_id
                ),
                None,
            )
            if existing is not None:
                if existing == event:
                    return existing
                raise CandidateLifecycleError(
                    "Runtime availability event identity conflicts with stored evidence."
                )
            updated = replace(
                ledger,
                availability_events=ledger.availability_events + (event,),
            )
            validate_ledger(updated)
            self._save(updated)
            return event

    def _save(self, ledger: CandidateLifecycleLedger) -> None:
        content = canonical_json_bytes(ledger_to_wire(ledger))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class CandidateLifecycleCoordinator:
    """Validates and records material lifecycle events without deriving signals."""

    def __init__(
        self,
        store: CandidateLifecycleStore,
        *,
        policy: CandidateLifecyclePolicy,
    ) -> None:
        validate_candidate_lifecycle_policy(policy)
        self.store = store
        self.policy = policy

    def discover(
        self,
        *,
        symbol: str,
        session_date: str,
        originating_evidence_family: str,
        evidence_fingerprint: str,
        source_identity: str,
        occurred_at: datetime,
        provider_timestamp: datetime,
        receipt_timestamp: datetime,
        reason: str,
    ) -> CandidateLifecycleResult:
        normalized_symbol = normalize_symbol(symbol)
        normalized_session = normalize_session_date(session_date)
        normalized_family = require_text(
            originating_evidence_family, "Originating evidence family"
        ).upper()
        opportunity = expected_opportunity_id(
            normalized_symbol, normalized_session, normalized_family
        )
        existing = self.snapshot(opportunity)
        if existing is not None:
            evidence = require_sha256(evidence_fingerprint, "Candidate evidence")
            source = require_text(
                source_identity, "Candidate evidence source identity"
            )
            occurred = aware_text(occurred_at, "Candidate event timestamp")
            provider = aware_text(
                provider_timestamp, "Candidate provider timestamp"
            )
            receipt = aware_text(receipt_timestamp, "Candidate receipt timestamp")
            normalized_reason = require_text(reason, "Candidate lifecycle reason")
            ledger = self.store.load()
            prior_discovery = next(
                (
                    item
                    for item in reversed(ledger.events)
                    if item.opportunity_id == opportunity
                    and item.event_type == DISCOVERY_EVENT
                    and item.evidence_fingerprint == evidence
                    and item.source_identity == source
                ),
                None,
            )
            if prior_discovery is not None:
                if not event_matches_request(
                    prior_discovery,
                    evidence_fingerprint=evidence,
                    source_identity=source,
                    occurred_at=occurred,
                    provider_timestamp=provider,
                    receipt_timestamp=receipt,
                    reason=normalized_reason,
                    next_state=DISCOVERED,
                    material_delta_kind=DISCOVERY_MEMBERSHIP_CHANGED,
                    requested_setup_family="",
                    event_type=DISCOVERY_EVENT,
                    policy_fingerprint=self.policy.fingerprint,
                ):
                    raise CandidateLifecycleError(
                        "Candidate lifecycle event replay conflicts with stored evidence."
                    )
                latest_event = next(
                    item
                    for item in reversed(ledger.events)
                    if item.opportunity_id == opportunity
                )
                if latest_event.event_id == prior_discovery.event_id:
                    return CandidateLifecycleResult(
                        status=DUPLICATE,
                        event=prior_discovery,
                        snapshot=existing,
                    )
                return CandidateLifecycleResult(
                    status=NO_CHANGE,
                    event=None,
                    snapshot=existing,
                )
        return self._record(
            opportunity_id=opportunity,
            symbol=normalized_symbol,
            session_date=normalized_session,
            originating_evidence_family=normalized_family,
            next_state=(existing.current_state if existing is not None else DISCOVERED),
            evidence_fingerprint=evidence_fingerprint,
            source_identity=source_identity,
            occurred_at=occurred_at,
            provider_timestamp=provider_timestamp,
            receipt_timestamp=receipt_timestamp,
            reason=reason,
            material_delta_kind=DISCOVERY_MEMBERSHIP_CHANGED,
            requested_event_type=(
                EVIDENCE_REFRESH_EVENT if existing is not None else DISCOVERY_EVENT
            ),
        )

    def transition(
        self,
        *,
        opportunity_id: str,
        next_state: str,
        evidence_fingerprint: str,
        source_identity: str,
        occurred_at: datetime,
        provider_timestamp: datetime,
        receipt_timestamp: datetime,
        reason: str,
        material_delta_kind: str,
        setup_family: str = "",
        create_new_setup: bool = False,
    ) -> CandidateLifecycleResult:
        if str(next_state).strip().upper() == DATA_STALE:
            raise CandidateLifecycleError(
                "Use mark_stale so stale evidence remains an explicit boundary."
            )
        snapshot = self.snapshot(opportunity_id)
        if snapshot is None:
            raise CandidateLifecycleError("Candidate opportunity does not exist.")
        return self._record(
            opportunity_id=snapshot.opportunity_id,
            symbol=snapshot.symbol,
            session_date=snapshot.session_date,
            originating_evidence_family=snapshot.originating_evidence_family,
            next_state=next_state,
            evidence_fingerprint=evidence_fingerprint,
            source_identity=source_identity,
            occurred_at=occurred_at,
            provider_timestamp=provider_timestamp,
            receipt_timestamp=receipt_timestamp,
            reason=reason,
            material_delta_kind=material_delta_kind,
            setup_family=setup_family,
            create_new_setup=create_new_setup,
        )

    def mark_stale(
        self,
        *,
        opportunity_id: str,
        evidence_fingerprint: str,
        source_identity: str,
        occurred_at: datetime,
        provider_timestamp: datetime,
        receipt_timestamp: datetime,
        reason: str,
    ) -> CandidateLifecycleResult:
        snapshot = self.snapshot(opportunity_id)
        if snapshot is None:
            raise CandidateLifecycleError("Candidate opportunity does not exist.")
        return self._record(
            opportunity_id=snapshot.opportunity_id,
            symbol=snapshot.symbol,
            session_date=snapshot.session_date,
            originating_evidence_family=snapshot.originating_evidence_family,
            next_state=DATA_STALE,
            evidence_fingerprint=evidence_fingerprint,
            source_identity=source_identity,
            occurred_at=occurred_at,
            provider_timestamp=provider_timestamp,
            receipt_timestamp=receipt_timestamp,
            reason=reason,
            material_delta_kind=DATA_BECAME_STALE,
            requested_event_type=DATA_STALE_EVENT,
        )

    def recover(
        self,
        *,
        opportunity_id: str,
        evidence_fingerprint: str,
        source_identity: str,
        occurred_at: datetime,
        provider_timestamp: datetime,
        receipt_timestamp: datetime,
        reason: str,
    ) -> CandidateLifecycleResult:
        snapshot = self.snapshot(opportunity_id)
        if snapshot is None:
            raise CandidateLifecycleError("Candidate opportunity does not exist.")
        if snapshot.current_state != DATA_STALE:
            raise CandidateLifecycleError(
                "Candidate data recovery requires a current DATA_STALE state."
            )
        if not snapshot.last_non_stale_state:
            raise CandidateLifecycleError(
                "Candidate data recovery has no prior noneligible state."
            )
        return self._record(
            opportunity_id=snapshot.opportunity_id,
            symbol=snapshot.symbol,
            session_date=snapshot.session_date,
            originating_evidence_family=snapshot.originating_evidence_family,
            next_state=snapshot.last_non_stale_state,
            evidence_fingerprint=evidence_fingerprint,
            source_identity=source_identity,
            occurred_at=occurred_at,
            provider_timestamp=provider_timestamp,
            receipt_timestamp=receipt_timestamp,
            reason=reason,
            material_delta_kind=DATA_RECOVERED_DELTA,
            requested_event_type=DATA_RECOVERED_EVENT,
        )

    def record_availability(
        self,
        *,
        scope: str,
        status: str,
        occurred_at: datetime,
        source_identity: str,
        evidence_fingerprint: str,
        reason: str,
    ) -> RuntimeAvailabilityEvent:
        normalized_scope = str(scope).strip().upper()
        normalized_status = str(status).strip().upper()
        if normalized_scope not in AVAILABILITY_SCOPES:
            raise CandidateLifecycleError("Runtime availability scope is unsupported.")
        if normalized_status not in AVAILABILITY_STATUSES:
            raise CandidateLifecycleError("Runtime availability status is unsupported.")
        occurred = aware_text(occurred_at, "Availability timestamp")
        source = require_text(source_identity, "Availability source identity")
        evidence = require_sha256(evidence_fingerprint, "Availability evidence")
        normalized_reason = require_text(reason, "Availability reason")
        event_id = expected_availability_event_id(
            scope=normalized_scope,
            status=normalized_status,
            occurred_at=occurred,
            source_identity=source,
            evidence_fingerprint=evidence,
            policy_fingerprint=self.policy.fingerprint,
        )
        ledger = self.store.load()
        previous_in_scope = next(
            (
                item
                for item in reversed(ledger.availability_events)
                if item.scope == normalized_scope
            ),
            None,
        )
        if (
            previous_in_scope is not None
            and aware_datetime(occurred) < aware_datetime(previous_in_scope.occurred_at)
        ):
            raise CandidateLifecycleError(
                "Runtime availability event predates the latest event in its scope."
            )
        if normalized_status == AVAILABILITY_RECOVERED and (
            previous_in_scope is None
            or previous_in_scope.status
            not in {AVAILABILITY_FAILED, AVAILABILITY_MISSED}
        ):
            raise CandidateLifecycleError(
                "Runtime availability recovery requires a prior failure or missed event."
            )
        existing = next(
            (
                item
                for item in ledger.availability_events
                if item.event_id == event_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.reason != normalized_reason
                or existing.evidence_fingerprint != evidence
            ):
                raise CandidateLifecycleError(
                    "Runtime availability event replay conflicts with stored evidence."
                )
            return existing
        event = RuntimeAvailabilityEvent(
            sequence=len(ledger.availability_events) + 1,
            event_id=event_id,
            scope=normalized_scope,
            status=normalized_status,
            occurred_at=occurred,
            source_identity=source,
            evidence_fingerprint=evidence,
            reason=normalized_reason,
            policy_version=self.policy.policy_version,
            policy_fingerprint=self.policy.fingerprint,
            cooldown_seconds=self.policy.cooldown_seconds,
            hysteresis_profile=self.policy.hysteresis_profile,
            minimum_delta_profile=self.policy.minimum_delta_profile,
            quote_only_events_create_cycles=(
                self.policy.quote_only_events_create_cycles
            ),
        )
        event = replace(event, fingerprint=availability_event_fingerprint(event))
        return self.store.append_availability_event(event)

    def snapshot(self, opportunity_id: str) -> CandidateLifecycleSnapshot | None:
        return lifecycle_snapshots(self.store.load()).get(str(opportunity_id).strip())

    def snapshots(self) -> dict[str, CandidateLifecycleSnapshot]:
        return lifecycle_snapshots(self.store.load())

    def _record(
        self,
        *,
        opportunity_id: str,
        symbol: str,
        session_date: str,
        originating_evidence_family: str,
        next_state: str,
        evidence_fingerprint: str,
        source_identity: str,
        occurred_at: datetime,
        provider_timestamp: datetime,
        receipt_timestamp: datetime,
        reason: str,
        material_delta_kind: str,
        setup_family: str = "",
        create_new_setup: bool = False,
        requested_event_type: str = "",
    ) -> CandidateLifecycleResult:
        normalized_next = str(next_state).strip().upper()
        if normalized_next not in CANDIDATE_STATES:
            raise CandidateLifecycleError("Candidate lifecycle state is unsupported.")
        normalized_delta = str(material_delta_kind).strip().upper()
        if normalized_delta not in MATERIAL_DELTA_KINDS:
            raise CandidateLifecycleError(
                "Candidate lifecycle event lacks a recognized material delta."
            )
        evidence = require_sha256(evidence_fingerprint, "Candidate evidence")
        source = require_text(source_identity, "Candidate evidence source identity")
        normalized_reason = require_text(reason, "Candidate lifecycle reason")
        occurred = aware_text(occurred_at, "Candidate event timestamp")
        provider = aware_text(provider_timestamp, "Candidate provider timestamp")
        receipt = aware_text(receipt_timestamp, "Candidate receipt timestamp")
        requested_family = str(setup_family).strip().upper()
        if requested_family and requested_family not in SUPPORTED_SETUP_FAMILIES:
            raise CandidateLifecycleError("Candidate setup family is unsupported.")

        ledger = self.store.load()
        snapshots = lifecycle_snapshots(ledger)
        current = snapshots.get(opportunity_id)
        current_event = (
            next(
                item
                for item in reversed(ledger.events)
                if item.event_id == current.latest_event_id
            )
            if current is not None
            else None
        )
        current_state = current.current_state if current is not None else ""
        event_type = requested_event_type or (
            EVIDENCE_REFRESH_EVENT
            if current_state == normalized_next
            else STATE_TRANSITION_EVENT
        )
        if current is None:
            if event_type != DISCOVERY_EVENT or normalized_next != DISCOVERED:
                raise CandidateLifecycleError(
                    "Candidate lifecycle must begin with DISCOVERED evidence."
                )
        else:
            prior_evidence = next(
                (
                    item
                    for item in ledger.events
                    if item.opportunity_id == opportunity_id
                    and item.evidence_fingerprint == evidence
                    and item.source_identity == source
                ),
                None,
            )
            if prior_evidence is not None:
                return CandidateLifecycleResult(
                    status=NO_CHANGE, event=None, snapshot=current
                )
            if current.latest_evidence_fingerprint == evidence:
                if current.current_state == normalized_next:
                    return CandidateLifecycleResult(
                        status=NO_CHANGE, event=None, snapshot=current
                    )
                raise CandidateLifecycleError(
                    "Identical candidate evidence cannot produce a conflicting state."
                )
            if aware_datetime(occurred) < aware_datetime(current.updated_at):
                raise CandidateLifecycleError(
                    "Candidate lifecycle event predates the current persisted state."
                )
            if current.current_state == COOLDOWN and normalized_next == WATCHING:
                cooldown_ends = aware_datetime(current.updated_at) + timedelta(
                    seconds=current_event.cooldown_seconds
                )
                if aware_datetime(occurred) < cooldown_ends:
                    raise CandidateLifecycleError(
                        "Candidate cooldown has not reached its configured expiry."
                    )

        previous_state = current_state
        if event_type == EVIDENCE_REFRESH_EVENT:
            if current is None or normalized_next != previous_state:
                raise CandidateLifecycleError(
                    "Candidate evidence refresh cannot change lifecycle state."
                )
        elif event_type == DATA_STALE_EVENT:
            if current is None or normalized_next != DATA_STALE or previous_state == DATA_STALE:
                raise CandidateLifecycleError(
                    "Candidate stale event requires a non-stale current state."
                )
            if DATA_STALE not in LEGAL_TRANSITIONS.get(previous_state, frozenset()):
                raise CandidateLifecycleError(
                    "Candidate state cannot transition to DATA_STALE."
                )
        elif event_type == DATA_RECOVERED_EVENT:
            if current is None or previous_state != DATA_STALE:
                raise CandidateLifecycleError(
                    "Candidate recovery requires a DATA_STALE current state."
                )
            if normalized_next != current.last_non_stale_state:
                raise CandidateLifecycleError(
                    "Candidate recovery must return to the last valid noneligible state."
                )
        elif event_type == DISCOVERY_EVENT:
            if current is not None:
                raise CandidateLifecycleError(
                    "Candidate opportunity cannot be rediscovered in place."
                )
        elif normalized_next not in LEGAL_TRANSITIONS.get(
            previous_state, frozenset()
        ):
            raise CandidateLifecycleError(
                f"Illegal candidate lifecycle transition: {previous_state} -> {normalized_next}."
            )

        setup_id, normalized_setup_family, setup_sequence, predecessor_setup_id = (
            resolve_setup_identity(
                current,
                next_state=normalized_next,
                requested_family=requested_family,
                create_new_setup=create_new_setup,
            )
        )
        validate_state_setup_family(normalized_next, normalized_setup_family)
        previous_event_id = current.latest_event_id if current is not None else ""
        event_id = expected_candidate_event_id(
            opportunity_id=opportunity_id,
            next_state=normalized_next,
            evidence_fingerprint=evidence,
            occurred_at=occurred,
            source_identity=source,
            material_delta_kind=normalized_delta,
            event_type=event_type,
            provider_timestamp=provider,
            receipt_timestamp=receipt,
            policy_fingerprint=self.policy.fingerprint,
            setup_id=setup_id,
            previous_event_id=previous_event_id,
        )
        existing = next(
            (item for item in ledger.events if item.event_id == event_id), None
        )
        if existing is not None:
            if not event_matches_request(
                existing,
                evidence_fingerprint=evidence,
                source_identity=source,
                occurred_at=occurred,
                provider_timestamp=provider,
                receipt_timestamp=receipt,
                reason=normalized_reason,
                next_state=normalized_next,
                material_delta_kind=normalized_delta,
                requested_setup_family=normalized_setup_family,
                event_type=event_type,
                policy_fingerprint=self.policy.fingerprint,
            ):
                raise CandidateLifecycleError(
                    "Candidate lifecycle event replay conflicts with stored evidence."
                )
            return CandidateLifecycleResult(
                status=DUPLICATE,
                event=existing,
                snapshot=snapshots.get(opportunity_id),
            )
        event = CandidateLifecycleEvent(
            sequence=len(ledger.events) + 1,
            event_id=event_id,
            opportunity_id=opportunity_id,
            symbol=symbol,
            session_date=session_date,
            originating_evidence_family=originating_evidence_family,
            event_type=event_type,
            previous_state=previous_state,
            next_state=normalized_next,
            occurred_at=occurred,
            provider_timestamp=provider,
            receipt_timestamp=receipt,
            source_identity=source,
            evidence_fingerprint=evidence,
            material_delta_kind=normalized_delta,
            reason=normalized_reason,
            policy_version=self.policy.policy_version,
            policy_fingerprint=self.policy.fingerprint,
            cooldown_seconds=self.policy.cooldown_seconds,
            hysteresis_profile=self.policy.hysteresis_profile,
            minimum_delta_profile=self.policy.minimum_delta_profile,
            quote_only_events_create_cycles=(
                self.policy.quote_only_events_create_cycles
            ),
            setup_id=setup_id,
            setup_family=normalized_setup_family,
            setup_sequence=setup_sequence,
            predecessor_setup_id=predecessor_setup_id,
            previous_event_id=previous_event_id,
        )
        event = replace(event, fingerprint=lifecycle_event_fingerprint(event))
        self.store.append_event(event)
        updated = self.snapshot(opportunity_id)
        return CandidateLifecycleResult(status=CREATED, event=event, snapshot=updated)


def expected_opportunity_id(
    symbol: str, session_date: str, originating_evidence_family: str
) -> str:
    return stable_hash(
        "candidate-opportunity-v1",
        normalize_symbol(symbol),
        normalize_session_date(session_date),
        require_text(
            originating_evidence_family, "Originating evidence family"
        ).upper(),
    )


def expected_setup_id(opportunity_id: str, setup_family: str, sequence: int) -> str:
    require_sha256(opportunity_id, "Opportunity identity")
    normalized_family = str(setup_family).strip().upper()
    if normalized_family not in SUPPORTED_SETUP_FAMILIES:
        raise CandidateLifecycleError("Candidate setup family is unsupported.")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise CandidateLifecycleError("Candidate setup sequence must be positive.")
    return stable_hash(
        "candidate-setup-v1", opportunity_id, normalized_family, str(sequence)
    )


def expected_candidate_event_id(
    *,
    opportunity_id: str,
    next_state: str,
    evidence_fingerprint: str,
    occurred_at: str,
    source_identity: str,
    material_delta_kind: str,
    event_type: str,
    provider_timestamp: str,
    receipt_timestamp: str,
    policy_fingerprint: str,
    setup_id: str,
    previous_event_id: str,
) -> str:
    return stable_hash(
        "candidate-lifecycle-event-v1",
        opportunity_id,
        next_state,
        evidence_fingerprint,
        occurred_at,
        source_identity,
        material_delta_kind,
        event_type,
        provider_timestamp,
        receipt_timestamp,
        policy_fingerprint,
        setup_id,
        previous_event_id,
    )


def expected_availability_event_id(
    *,
    scope: str,
    status: str,
    occurred_at: str,
    source_identity: str,
    evidence_fingerprint: str,
    policy_fingerprint: str,
) -> str:
    return stable_hash(
        "candidate-availability-event-v1",
        scope,
        status,
        occurred_at,
        source_identity,
        evidence_fingerprint,
        policy_fingerprint,
    )


def resolve_setup_identity(
    current: CandidateLifecycleSnapshot | None,
    *,
    next_state: str,
    requested_family: str,
    create_new_setup: bool = False,
) -> tuple[str, str, int, str]:
    if current is None:
        if requested_family:
            raise CandidateLifecycleError(
                "Discovery evidence cannot create a setup identity."
            )
        return "", "", 0, ""
    if next_state in {DATA_STALE, INVALIDATED, COOLDOWN, WATCHING} and not requested_family:
        return (
            current.current_setup_id,
            current.current_setup_family,
            current.current_setup_sequence,
            "",
        )
    if next_state not in SETUP_BOUND_STATES and not requested_family:
        return (
            current.current_setup_id,
            current.current_setup_family,
            current.current_setup_sequence,
            "",
        )
    if requested_family and next_state not in SETUP_BOUND_STATES:
        raise CandidateLifecycleError(
            "A new setup identity requires a setup-bound candidate state."
        )
    if create_new_setup and next_state not in SETUP_BOUND_STATES:
        raise CandidateLifecycleError(
            "A new setup sequence requires a setup-bound candidate state."
        )
    family = requested_family or current.current_setup_family
    if not family:
        raise CandidateLifecycleError(
            "Setup-bound candidate state requires an explicit setup family."
        )
    if (
        current.current_setup_family == family
        and current.current_setup_id
        and not create_new_setup
    ):
        return (
            current.current_setup_id,
            family,
            current.current_setup_sequence,
            "",
        )
    sequence = current.current_setup_sequence + 1
    predecessor = current.current_setup_id
    return (
        expected_setup_id(current.opportunity_id, family, sequence),
        family,
        sequence,
        predecessor,
    )


def lifecycle_snapshots(
    ledger: CandidateLifecycleLedger,
) -> dict[str, CandidateLifecycleSnapshot]:
    snapshots: dict[str, CandidateLifecycleSnapshot] = {}
    for event in ledger.events:
        prior = snapshots.get(event.opportunity_id)
        if event.next_state == DATA_STALE:
            last_non_stale = (
                prior.last_non_stale_state
                if prior is not None and prior.current_state == EXECUTION_ELIGIBLE
                else (
                    prior.current_state
                    if prior is not None and prior.current_state != DATA_STALE
                    and prior.current_state != EXECUTION_ELIGIBLE
                    else (prior.last_non_stale_state if prior is not None else "")
                )
            )
        elif event.event_type == DATA_RECOVERED_EVENT:
            last_non_stale = event.next_state
        elif event.next_state == EXECUTION_ELIGIBLE:
            last_non_stale = prior.last_non_stale_state if prior is not None else ""
        else:
            last_non_stale = event.next_state
        snapshots[event.opportunity_id] = CandidateLifecycleSnapshot(
            opportunity_id=event.opportunity_id,
            symbol=event.symbol,
            session_date=event.session_date,
            originating_evidence_family=event.originating_evidence_family,
            current_state=event.next_state,
            last_non_stale_state=last_non_stale,
            latest_event_id=event.event_id,
            latest_evidence_fingerprint=event.evidence_fingerprint,
            current_setup_id=event.setup_id,
            current_setup_family=event.setup_family,
            current_setup_sequence=event.setup_sequence,
            latest_policy_fingerprint=event.policy_fingerprint,
            updated_at=event.occurred_at,
        )
    return snapshots


def validate_ledger(ledger: CandidateLifecycleLedger) -> None:
    if ledger.schema_version != CANDIDATE_LIFECYCLE_SCHEMA_VERSION:
        raise CandidateLifecycleError("Candidate lifecycle ledger schema is unsupported.")
    if ledger.profile != CANDIDATE_LIFECYCLE_PROFILE:
        raise CandidateLifecycleError("Candidate lifecycle ledger profile is unsupported.")
    replay = CandidateLifecycleLedger()
    seen_event_ids: set[str] = set()
    for expected_sequence, event in enumerate(ledger.events, start=1):
        validate_lifecycle_event(event)
        if event.sequence != expected_sequence:
            raise CandidateLifecycleError("Candidate lifecycle event sequence is invalid.")
        if event.event_id in seen_event_ids:
            raise CandidateLifecycleError("Candidate lifecycle event identity is duplicated.")
        seen_event_ids.add(event.event_id)
        snapshots = lifecycle_snapshots(replay)
        prior = snapshots.get(event.opportunity_id)
        prior_event = (
            next(
                item
                for item in reversed(replay.events)
                if item.event_id == prior.latest_event_id
            )
            if prior is not None
            else None
        )
        expected_previous = prior.current_state if prior is not None else ""
        expected_previous_event = prior.latest_event_id if prior is not None else ""
        if event.previous_state != expected_previous:
            raise CandidateLifecycleError("Candidate lifecycle previous state is contradictory.")
        if event.previous_event_id != expected_previous_event:
            raise CandidateLifecycleError("Candidate lifecycle predecessor event is contradictory.")
        validate_replayed_transition(prior, prior_event, event)
        replay = replace(replay, events=replay.events + (event,))
    seen_availability_ids: set[str] = set()
    availability_by_scope: dict[str, RuntimeAvailabilityEvent] = {}
    for expected_sequence, event in enumerate(ledger.availability_events, start=1):
        validate_availability_event(event)
        if event.sequence != expected_sequence:
            raise CandidateLifecycleError("Availability event sequence is invalid.")
        if event.event_id in seen_availability_ids:
            raise CandidateLifecycleError("Availability event identity is duplicated.")
        seen_availability_ids.add(event.event_id)
        previous = availability_by_scope.get(event.scope)
        if previous is not None and aware_datetime(event.occurred_at) < aware_datetime(
            previous.occurred_at
        ):
            raise CandidateLifecycleError("Availability event chronology regressed.")
        if event.status == AVAILABILITY_RECOVERED and (
            previous is None
            or previous.status not in {AVAILABILITY_FAILED, AVAILABILITY_MISSED}
        ):
            raise CandidateLifecycleError(
                "Availability recovery lacks a prior failure or missed event."
            )
        availability_by_scope[event.scope] = event


def validate_replayed_transition(
    prior: CandidateLifecycleSnapshot | None,
    prior_event: CandidateLifecycleEvent | None,
    event: CandidateLifecycleEvent,
) -> None:
    if prior is None:
        if event.event_type != DISCOVERY_EVENT or event.next_state != DISCOVERED:
            raise CandidateLifecycleError(
                "Candidate lifecycle does not begin with DISCOVERED evidence."
            )
        return
    if aware_datetime(event.occurred_at) < aware_datetime(prior.updated_at):
        raise CandidateLifecycleError("Candidate lifecycle event chronology regressed.")
    if prior.current_state == COOLDOWN and event.next_state == WATCHING:
        if prior_event is None:
            raise CandidateLifecycleError("Candidate cooldown evidence is incomplete.")
        cooldown_ends = aware_datetime(prior.updated_at) + timedelta(
            seconds=prior_event.cooldown_seconds
        )
        if aware_datetime(event.occurred_at) < cooldown_ends:
            raise CandidateLifecycleError(
                "Candidate cooldown expired earlier than its persisted policy allows."
            )
    if event.event_type == EVIDENCE_REFRESH_EVENT:
        if event.next_state != prior.current_state:
            raise CandidateLifecycleError("Evidence refresh changed candidate state.")
    elif event.event_type == DATA_STALE_EVENT:
        if event.next_state != DATA_STALE or prior.current_state == DATA_STALE:
            raise CandidateLifecycleError("Candidate stale transition is invalid.")
        if DATA_STALE not in LEGAL_TRANSITIONS.get(prior.current_state, frozenset()):
            raise CandidateLifecycleError("Candidate stale transition is illegal.")
    elif event.event_type == DATA_RECOVERED_EVENT:
        if prior.current_state != DATA_STALE or event.next_state != prior.last_non_stale_state:
            raise CandidateLifecycleError("Candidate stale recovery is contradictory.")
    elif event.event_type == DISCOVERY_EVENT:
        raise CandidateLifecycleError("Candidate opportunity was rediscovered in place.")
    elif event.next_state not in LEGAL_TRANSITIONS.get(prior.current_state, frozenset()):
        raise CandidateLifecycleError(
            f"Illegal candidate lifecycle transition: {prior.current_state} -> {event.next_state}."
        )
    expected_setup = resolve_setup_identity(
        prior,
        next_state=event.next_state,
        requested_family=(
            event.setup_family
            if event.setup_family != prior.current_setup_family
            else ""
        ),
        create_new_setup=(
            bool(event.predecessor_setup_id)
            and event.setup_id != prior.current_setup_id
        ),
    )
    if (
        event.setup_id,
        event.setup_family,
        event.setup_sequence,
        event.predecessor_setup_id,
    ) != expected_setup:
        raise CandidateLifecycleError("Candidate setup identity chain is contradictory.")


def validate_lifecycle_event(event: CandidateLifecycleEvent) -> None:
    if event.schema_version != CANDIDATE_LIFECYCLE_SCHEMA_VERSION:
        raise CandidateLifecycleError("Candidate lifecycle event schema is unsupported.")
    if event.profile != CANDIDATE_LIFECYCLE_PROFILE:
        raise CandidateLifecycleError("Candidate lifecycle event profile is unsupported.")
    require_sha256(event.event_id, "Candidate event identity")
    require_sha256(event.opportunity_id, "Candidate opportunity identity")
    normalize_symbol(event.symbol)
    normalize_session_date(event.session_date)
    require_text(event.originating_evidence_family, "Originating evidence family")
    if event.opportunity_id != expected_opportunity_id(
        event.symbol, event.session_date, event.originating_evidence_family
    ):
        raise CandidateLifecycleError("Candidate opportunity identity is contradictory.")
    if event.originating_evidence_family != event.originating_evidence_family.upper():
        raise CandidateLifecycleError(
            "Candidate originating evidence family is not canonical."
        )
    event_session_date = (
        aware_datetime(event.occurred_at).astimezone(EASTERN_TZ).date().isoformat()
    )
    if event_session_date != event.session_date:
        raise CandidateLifecycleError(
            "Candidate event timestamp does not match its market session date."
        )
    if event.event_type not in EVENT_TYPES:
        raise CandidateLifecycleError("Candidate lifecycle event type is unsupported.")
    if event.previous_state and event.previous_state not in CANDIDATE_STATES:
        raise CandidateLifecycleError("Candidate previous state is unsupported.")
    if event.next_state not in CANDIDATE_STATES:
        raise CandidateLifecycleError("Candidate next state is unsupported.")
    aware_text(event.occurred_at, "Candidate event timestamp")
    aware_text(event.provider_timestamp, "Candidate provider timestamp")
    aware_text(event.receipt_timestamp, "Candidate receipt timestamp")
    require_text(event.source_identity, "Candidate evidence source identity")
    require_sha256(event.evidence_fingerprint, "Candidate evidence")
    require_text(event.reason, "Candidate lifecycle reason")
    if event.material_delta_kind not in MATERIAL_DELTA_KINDS:
        raise CandidateLifecycleError("Candidate material delta is unsupported.")
    policy = CandidateLifecyclePolicy(
        policy_version=event.policy_version,
        cooldown_seconds=event.cooldown_seconds,
        hysteresis_profile=event.hysteresis_profile,
        minimum_delta_profile=event.minimum_delta_profile,
        quote_only_events_create_cycles=event.quote_only_events_create_cycles,
    )
    validate_candidate_lifecycle_policy(policy)
    if event.policy_fingerprint != policy.fingerprint:
        raise CandidateLifecycleError("Candidate lifecycle policy fingerprint is invalid.")
    validate_state_setup_family(event.next_state, event.setup_family)
    if event.event_id != expected_candidate_event_id(
        opportunity_id=event.opportunity_id,
        next_state=event.next_state,
        evidence_fingerprint=event.evidence_fingerprint,
        occurred_at=event.occurred_at,
        source_identity=event.source_identity,
        material_delta_kind=event.material_delta_kind,
        event_type=event.event_type,
        provider_timestamp=event.provider_timestamp,
        receipt_timestamp=event.receipt_timestamp,
        policy_fingerprint=event.policy_fingerprint,
        setup_id=event.setup_id,
        previous_event_id=event.previous_event_id,
    ):
        raise CandidateLifecycleError("Candidate lifecycle event identity is invalid.")
    if event.setup_id:
        if event.setup_id != expected_setup_id(
            event.opportunity_id, event.setup_family, event.setup_sequence
        ):
            raise CandidateLifecycleError("Candidate setup identity is contradictory.")
    elif event.setup_family or event.setup_sequence or event.predecessor_setup_id:
        raise CandidateLifecycleError("Candidate setup identity is incomplete.")
    if event.previous_event_id:
        require_sha256(event.previous_event_id, "Candidate predecessor event")
    if event.predecessor_setup_id:
        require_sha256(event.predecessor_setup_id, "Candidate predecessor setup")
    if event.fingerprint != lifecycle_event_fingerprint(event):
        raise CandidateLifecycleError("Candidate lifecycle event fingerprint is invalid.")


def validate_availability_event(event: RuntimeAvailabilityEvent) -> None:
    if event.schema_version != CANDIDATE_LIFECYCLE_SCHEMA_VERSION:
        raise CandidateLifecycleError("Availability event schema is unsupported.")
    if event.profile != CANDIDATE_LIFECYCLE_PROFILE:
        raise CandidateLifecycleError("Availability event profile is unsupported.")
    require_sha256(event.event_id, "Availability event identity")
    if event.scope not in AVAILABILITY_SCOPES:
        raise CandidateLifecycleError("Availability scope is unsupported.")
    if event.status not in AVAILABILITY_STATUSES:
        raise CandidateLifecycleError("Availability status is unsupported.")
    aware_text(event.occurred_at, "Availability timestamp")
    require_text(event.source_identity, "Availability source identity")
    require_sha256(event.evidence_fingerprint, "Availability evidence")
    require_text(event.reason, "Availability reason")
    policy = CandidateLifecyclePolicy(
        policy_version=event.policy_version,
        cooldown_seconds=event.cooldown_seconds,
        hysteresis_profile=event.hysteresis_profile,
        minimum_delta_profile=event.minimum_delta_profile,
        quote_only_events_create_cycles=event.quote_only_events_create_cycles,
    )
    validate_candidate_lifecycle_policy(policy)
    if event.policy_fingerprint != policy.fingerprint:
        raise CandidateLifecycleError("Availability policy fingerprint is invalid.")
    if event.event_id != expected_availability_event_id(
        scope=event.scope,
        status=event.status,
        occurred_at=event.occurred_at,
        source_identity=event.source_identity,
        evidence_fingerprint=event.evidence_fingerprint,
        policy_fingerprint=event.policy_fingerprint,
    ):
        raise CandidateLifecycleError("Availability event identity is invalid.")
    if event.fingerprint != availability_event_fingerprint(event):
        raise CandidateLifecycleError("Availability event fingerprint is invalid.")


def lifecycle_event_fingerprint(event: CandidateLifecycleEvent) -> str:
    return stable_hash(
        "candidate-lifecycle-record-v1",
        canonical_json_text(asdict(replace(event, fingerprint=""))),
    )


def availability_event_fingerprint(event: RuntimeAvailabilityEvent) -> str:
    return stable_hash(
        "candidate-availability-record-v1",
        canonical_json_text(asdict(replace(event, fingerprint=""))),
    )


def event_matches_request(
    event: CandidateLifecycleEvent,
    *,
    evidence_fingerprint: str,
    source_identity: str,
    occurred_at: str,
    provider_timestamp: str,
    receipt_timestamp: str,
    reason: str,
    next_state: str,
    material_delta_kind: str,
    requested_setup_family: str,
    event_type: str,
    policy_fingerprint: str,
) -> bool:
    return (
        event.evidence_fingerprint == evidence_fingerprint
        and event.source_identity == source_identity
        and event.occurred_at == occurred_at
        and event.provider_timestamp == provider_timestamp
        and event.receipt_timestamp == receipt_timestamp
        and event.reason == reason
        and event.next_state == next_state
        and event.material_delta_kind == material_delta_kind
        and event.event_type == event_type
        and event.policy_fingerprint == policy_fingerprint
        and (
            not requested_setup_family
            or event.setup_family == requested_setup_family
        )
    )


def ledger_to_wire(ledger: CandidateLifecycleLedger) -> dict[str, Any]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "events": [asdict(item) for item in ledger.events],
        "availability_events": [asdict(item) for item in ledger.availability_events],
    }


def ledger_from_wire(payload: object) -> CandidateLifecycleLedger:
    if not isinstance(payload, Mapping):
        raise CandidateLifecycleError("Candidate lifecycle evidence has an invalid shape.")
    events = payload.get("events")
    availability = payload.get("availability_events")
    if not isinstance(events, list) or not isinstance(availability, list):
        raise CandidateLifecycleError("Candidate lifecycle evidence has an invalid schema.")
    if any(not isinstance(item, Mapping) for item in events) or any(
        not isinstance(item, Mapping) for item in availability
    ):
        raise CandidateLifecycleError(
            "Candidate lifecycle evidence contains a malformed record."
        )
    try:
        return CandidateLifecycleLedger(
            schema_version=int(payload.get("schema_version", 0)),
            profile=str(payload.get("profile", "")),
            events=tuple(
                CandidateLifecycleEvent(**dict(item))
                for item in events
                if isinstance(item, Mapping)
            ),
            availability_events=tuple(
                RuntimeAvailabilityEvent(**dict(item))
                for item in availability
                if isinstance(item, Mapping)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise CandidateLifecycleError(
            "Candidate lifecycle evidence contains an invalid record."
        ) from exc


def normalize_symbol(value: object) -> str:
    symbol = str(value).strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise CandidateLifecycleError("Candidate symbol is invalid.")
    return symbol


def normalize_session_date(value: object) -> str:
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise CandidateLifecycleError("Candidate session date is invalid.") from exc
    return parsed.isoformat()


def require_text(value: object, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise CandidateLifecycleError(f"{label} is required.")
    return text


def require_sha256(value: object, label: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256_PATTERN.fullmatch(text):
        raise CandidateLifecycleError(f"{label} fingerprint is invalid.")
    return text


def aware_text(value: datetime | str, label: str) -> str:
    parsed = value if isinstance(value, datetime) else aware_datetime(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateLifecycleError(f"{label} must include a UTC offset.")
    return parsed.isoformat()


def aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateLifecycleError("Candidate timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateLifecycleError("Candidate timestamp must include a UTC offset.")
    return parsed


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(item) for item in parts).encode("utf-8")).hexdigest()


def validate_state_setup_family(state: str, setup_family: str) -> None:
    if state in {BREAKOUT_FORMING, BREAKOUT_CONFIRMED, FAILED_BREAKOUT} and setup_family not in {
        OPENING_BREAKOUT,
        CONTINUATION_BREAKOUT,
    }:
        raise CandidateLifecycleError(
            "Breakout lifecycle state requires an opening or continuation breakout setup."
        )
    if state == PULLBACK_FORMING and setup_family != PULLBACK:
        raise CandidateLifecycleError(
            "PULLBACK_FORMING requires a distinct PULLBACK setup identity."
        )
    if state == RECLAIM_FORMING and setup_family != RECLAIM:
        raise CandidateLifecycleError(
            "RECLAIM_FORMING requires a distinct RECLAIM setup identity."
        )


def validate_candidate_lifecycle_policy(policy: CandidateLifecyclePolicy) -> None:
    require_text(policy.policy_version, "Candidate lifecycle policy version")
    if (
        not isinstance(policy.cooldown_seconds, int)
        or isinstance(policy.cooldown_seconds, bool)
        or policy.cooldown_seconds < 0
    ):
        raise CandidateLifecycleError(
            "Candidate lifecycle cooldown must be a nonnegative integer."
        )
    require_text(policy.hysteresis_profile, "Candidate lifecycle hysteresis profile")
    require_text(policy.minimum_delta_profile, "Candidate lifecycle minimum-delta profile")
    if policy.quote_only_events_create_cycles:
        raise CandidateLifecycleError(
            "Quote-only events cannot create candidate decision cycles."
        )


def candidate_lifecycle_policy_fingerprint(
    policy: CandidateLifecyclePolicy,
) -> str:
    return stable_hash(
        "candidate-lifecycle-policy-v1",
        canonical_json_text(asdict(policy)),
    )


def canonical_json_text(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_json_bytes(payload: object) -> bytes:
    return (canonical_json_text(payload) + "\n").encode("utf-8")
