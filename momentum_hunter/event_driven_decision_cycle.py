"""Dormant event-driven decision-cycle evidence for continuous intraday work.

The contract consumes already-built PLAN-002A decisions. It does not discover
events, build plans, run risk or allocation, select a broker, or create orders.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Mapping

from momentum_hunter.candidate_lifecycle import (
    CANDIDATE_STATES,
    DATA_STALE,
    ENTRY_MISSED,
    EXHAUSTION_RISK,
    FAILED_BREAKOUT,
    INVALIDATED,
)
from momentum_hunter.continuous_plan_version import (
    DECISION_AUTHORIZED,
    DECISION_NO_TRADE,
    ContinuousPlanDecision,
    ContinuousPlanVersion,
    validate_decision,
    validate_plan_version,
)


EVENT_DECISION_SCHEMA_VERSION = 1
EVENT_DECISION_PROFILE = "event-driven-decision-cycle-v1"
EVENT_DECISION_AUTHORITY = "SYNTHETIC_NONLIVE_PRECURSOR"

NEW_CANDIDATE_DISCOVERED = "NEW_CANDIDATE_DISCOVERED"
CANDIDATE_STATE_CHANGED = "CANDIDATE_STATE_CHANGED"
MEANINGFUL_LEVEL_BREAK = "MEANINGFUL_LEVEL_BREAK"
TIME_NORMALIZED_VOLUME_ABNORMAL = "TIME_NORMALIZED_VOLUME_ABNORMAL"
DIRECT_CATALYST_ARRIVED = "DIRECT_CATALYST_ARRIVED"
MARKET_REGIME_CHANGED = "MARKET_REGIME_CHANGED"
SECTOR_REGIME_CHANGED = "SECTOR_REGIME_CHANGED"
EVENT_WINDOW_STABILIZED = "EVENT_WINDOW_STABILIZED"
SPREAD_BECAME_EXECUTABLE = "SPREAD_BECAME_EXECUTABLE"
PLAN_MATERIAL_REVISION = "PLAN_MATERIAL_REVISION"
PLAN_INVALIDATED = "PLAN_INVALIDATED"
DATA_BECAME_STALE = "DATA_BECAME_STALE"
QUOTE_UPDATE = "QUOTE_UPDATE"

TRIGGER_TYPES = frozenset(
    {
        NEW_CANDIDATE_DISCOVERED,
        CANDIDATE_STATE_CHANGED,
        MEANINGFUL_LEVEL_BREAK,
        TIME_NORMALIZED_VOLUME_ABNORMAL,
        DIRECT_CATALYST_ARRIVED,
        MARKET_REGIME_CHANGED,
        SECTOR_REGIME_CHANGED,
        EVENT_WINDOW_STABILIZED,
        SPREAD_BECAME_EXECUTABLE,
        PLAN_MATERIAL_REVISION,
        PLAN_INVALIDATED,
        DATA_BECAME_STALE,
        QUOTE_UPDATE,
    }
)

MATERIAL = "MATERIAL"
INSIGNIFICANT = "INSIGNIFICANT"
QUOTE_ONLY = "QUOTE_ONLY"
MATERIALITY_STATES = frozenset({MATERIAL, INSIGNIFICANT, QUOTE_ONLY})

CYCLE_CREATED = "CYCLE_CREATED"
QUOTE_ONLY_IGNORED = "QUOTE_ONLY_IGNORED"
INSUFFICIENT_DELTA_IGNORED = "INSUFFICIENT_DELTA_IGNORED"
COOLDOWN_SUPPRESSED = "COOLDOWN_SUPPRESSED"
RECEIPT_DISPOSITIONS = frozenset(
    {
        CYCLE_CREATED,
        QUOTE_ONLY_IGNORED,
        INSUFFICIENT_DELTA_IGNORED,
        COOLDOWN_SUPPRESSED,
    }
)

CREATED = "CREATED"
DUPLICATE = "DUPLICATE"

SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION = (
    "SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION"
)
NO_SELECTION = "NO_SELECTION"
SELECTION_RESULTS = frozenset(
    {SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION, NO_SELECTION}
)

SAFETY_TRIGGER_TYPES = frozenset(
    {
        MARKET_REGIME_CHANGED,
        SECTOR_REGIME_CHANGED,
        PLAN_INVALIDATED,
        DATA_BECAME_STALE,
    }
)
SAFETY_CANDIDATE_STATES = frozenset(
    {DATA_STALE, INVALIDATED, ENTRY_MISSED, FAILED_BREAKOUT, EXHAUSTION_RISK}
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LEASE_STATE = threading.local()


class EventDecisionCycleError(ValueError):
    """Raised when event-cycle evidence is invalid or contradictory."""


@dataclass(frozen=True)
class EventDecisionCyclePolicy:
    policy_version: str
    configuration_fingerprint: str
    cooldown_seconds: int
    minimum_delta_profile: str
    allowed_trigger_types: tuple[str, ...]
    quote_only_events_create_cycles: bool = False
    authority_profile: str = EVENT_DECISION_AUTHORITY

    @property
    def fingerprint(self) -> str:
        return fingerprint_payload(asdict(self))


@dataclass(frozen=True)
class DecisionTriggerEvidence:
    trigger_id: str
    trigger_type: str
    opportunity_id: str
    setup_id: str
    symbol: str
    session_date: str
    previous_candidate_state: str
    next_candidate_state: str
    occurred_at: str
    provider_timestamp: str
    receipt_timestamp: str
    source_identity: str
    source_evidence_id: str
    source_evidence_fingerprint: str
    material_delta_kind: str
    materiality: str
    candidate_event_id: str = ""
    schema_version: int = EVENT_DECISION_SCHEMA_VERSION
    profile: str = EVENT_DECISION_PROFILE
    fingerprint: str = ""

    @property
    def quote_only(self) -> bool:
        return self.trigger_type == QUOTE_UPDATE or self.materiality == QUOTE_ONLY


@dataclass(frozen=True)
class DecisionTriggerReceipt:
    sequence: int
    receipt_id: str
    recorded_at: str
    disposition: str
    reasons: tuple[str, ...]
    trigger: DecisionTriggerEvidence
    policy: EventDecisionCyclePolicy
    plan_version_id: str = ""
    plan_version_fingerprint: str = ""
    continuous_decision_id: str = ""
    continuous_decision_fingerprint: str = ""
    predecessor_cycle_id: str = ""
    cycle_id: str = ""
    schema_version: int = EVENT_DECISION_SCHEMA_VERSION
    profile: str = EVENT_DECISION_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class EventDrivenDecisionCycle:
    sequence: int
    cycle_id: str
    cycle_started_at: str
    decided_at: str
    trigger_id: str
    trigger_fingerprint: str
    trigger_type: str
    opportunity_id: str
    setup_id: str
    symbol: str
    session_date: str
    previous_candidate_state: str
    next_candidate_state: str
    plan_version_id: str
    plan_version_fingerprint: str
    plan_version_number: int
    intraday_plan_id: str
    continuous_decision_id: str
    continuous_decision_fingerprint: str
    risk_decision_id: str
    risk_decision_fingerprint: str
    risk_policy_fingerprint: str
    allocation_decision_cycle_id: str
    allocation_decision_fingerprint: str
    allocation_policy_fingerprint: str
    account_snapshot_fingerprint: str
    capability_registry_fingerprint: str
    mode: str
    decision_status: str
    selection_result: str
    final_authorized_quantity: str
    blockers: tuple[str, ...]
    predecessor_cycle_id: str
    predecessor_cycle_fingerprint: str
    policy_version: str
    policy_fingerprint: str
    configuration_fingerprint: str
    schema_version: int = EVENT_DECISION_SCHEMA_VERSION
    profile: str = EVENT_DECISION_PROFILE
    fingerprint: str = ""

    @property
    def selected(self) -> bool:
        return self.selection_result == SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION


@dataclass(frozen=True)
class EventDecisionCycleLedger:
    receipts: tuple[DecisionTriggerReceipt, ...] = field(default_factory=tuple)
    cycles: tuple[EventDrivenDecisionCycle, ...] = field(default_factory=tuple)
    schema_version: int = EVENT_DECISION_SCHEMA_VERSION
    profile: str = EVENT_DECISION_PROFILE


@dataclass(frozen=True)
class EventDecisionCycleResult:
    status: str
    receipt: DecisionTriggerReceipt
    cycle: EventDrivenDecisionCycle | None


def build_decision_trigger(
    *,
    trigger_type: str,
    opportunity_id: str,
    setup_id: str,
    symbol: str,
    session_date: str,
    previous_candidate_state: str,
    next_candidate_state: str,
    occurred_at: datetime,
    provider_timestamp: datetime,
    receipt_timestamp: datetime,
    source_identity: str,
    source_evidence_id: str,
    source_evidence_fingerprint: str,
    material_delta_kind: str,
    materiality: str,
    candidate_event_id: str = "",
) -> DecisionTriggerEvidence:
    """Create one deterministic trigger from already-observed evidence."""

    normalized_type = _required_text(trigger_type, "Trigger type").upper()
    if normalized_type not in TRIGGER_TYPES:
        raise EventDecisionCycleError("Decision trigger type is unsupported.")
    normalized_materiality = _required_text(
        materiality, "Trigger materiality"
    ).upper()
    if normalized_materiality not in MATERIALITY_STATES:
        raise EventDecisionCycleError("Decision trigger materiality is unsupported.")
    if normalized_type == QUOTE_UPDATE and normalized_materiality != QUOTE_ONLY:
        raise EventDecisionCycleError("Quote updates must remain quote-only evidence.")
    if normalized_type != QUOTE_UPDATE and normalized_materiality == QUOTE_ONLY:
        raise EventDecisionCycleError(
            "Quote-only materiality requires the explicit QUOTE_UPDATE trigger."
        )

    provider = _aware(provider_timestamp, "Trigger provider timestamp")
    occurred = _aware(occurred_at, "Trigger occurrence timestamp")
    received = _aware(receipt_timestamp, "Trigger receipt timestamp")
    if not provider <= occurred <= received:
        raise EventDecisionCycleError("Decision trigger chronology is invalid.")

    normalized_symbol = _symbol(symbol)
    normalized_opportunity = _sha256(opportunity_id, "Opportunity identity")
    normalized_setup = _optional_sha256(setup_id, "Setup identity")
    normalized_candidate_event = _optional_sha256(
        candidate_event_id, "Candidate event identity"
    )
    if normalized_type in {NEW_CANDIDATE_DISCOVERED, CANDIDATE_STATE_CHANGED} and (
        not normalized_candidate_event
    ):
        raise EventDecisionCycleError(
            "Candidate-driven triggers require a candidate lifecycle event identity."
        )
    previous_state = _candidate_state(previous_candidate_state, allow_empty=True)
    next_state = _candidate_state(next_candidate_state)
    core = {
        "trigger_type": normalized_type,
        "opportunity_id": normalized_opportunity,
        "setup_id": normalized_setup,
        "symbol": normalized_symbol,
        "session_date": _session_date(session_date),
        "previous_candidate_state": previous_state,
        "next_candidate_state": next_state,
        "occurred_at": occurred.isoformat(),
        "provider_timestamp": provider.isoformat(),
        "receipt_timestamp": received.isoformat(),
        "source_identity": _required_text(source_identity, "Trigger source identity"),
        "source_evidence_id": _required_text(
            source_evidence_id, "Trigger source evidence identity"
        ),
        "source_evidence_fingerprint": _sha256(
            source_evidence_fingerprint, "Trigger source evidence"
        ),
        "material_delta_kind": _required_text(
            material_delta_kind, "Trigger material delta"
        ).upper(),
        "materiality": normalized_materiality,
        "candidate_event_id": normalized_candidate_event,
        "schema_version": EVENT_DECISION_SCHEMA_VERSION,
        "profile": EVENT_DECISION_PROFILE,
    }
    identity = fingerprint_payload(core)
    trigger = DecisionTriggerEvidence(
        trigger_id=f"decision-trigger-{identity[:24]}",
        fingerprint=identity,
        **core,
    )
    validate_trigger(trigger)
    return trigger


class EventDecisionCycleStore:
    """Atomic explicit-path store for immutable trigger receipts and cycles."""

    def __init__(self, path: Path, *, lease_timeout_seconds: float = 5.0) -> None:
        self.path = Path(path)
        timeout = float(lease_timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise EventDecisionCycleError(
                "Event decision-cycle lease timeout must be positive and finite."
            )
        self.lease_timeout_seconds = timeout
        resolved = self.path.resolve()
        self.lease_path = resolved.with_name(f".{resolved.name}.lock")
        self._lock = _path_lock(self.path)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize a full read/validate/append/write transaction across processes."""

        with self._lock:
            resolved = self.path.resolve()
            depths = _lease_depths()
            current_depth = depths.get(resolved, 0)
            if current_depth:
                depths[resolved] = current_depth + 1
                try:
                    yield
                finally:
                    depths[resolved] -= 1
                return

            with _exclusive_path_lease(
                self.lease_path,
                timeout_seconds=self.lease_timeout_seconds,
            ):
                depths[resolved] = 1
                try:
                    yield
                finally:
                    depths.pop(resolved, None)

    def load(self) -> EventDecisionCycleLedger:
        with self._lock:
            if not self.path.exists():
                return EventDecisionCycleLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise EventDecisionCycleError(
                    f"Event decision-cycle ledger cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def save(self, ledger: EventDecisionCycleLedger) -> None:
        with self.transaction():
            validate_ledger(ledger)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(ledger)))


class EventDecisionCycleCoordinator:
    """Records meaningful non-live decisions without executing downstream work."""

    def __init__(
        self,
        store: EventDecisionCycleStore,
        *,
        policy: EventDecisionCyclePolicy,
    ) -> None:
        validate_policy(policy)
        self.store = store
        self.policy = policy

    def process(
        self,
        trigger: DecisionTriggerEvidence,
        *,
        recorded_at: datetime,
        cycle_started_at: datetime | None = None,
        plan_version: ContinuousPlanVersion | None = None,
        decision: ContinuousPlanDecision | None = None,
    ) -> EventDecisionCycleResult:
        with self.store.transaction():
            return self._process_locked(
                trigger,
                recorded_at=recorded_at,
                cycle_started_at=cycle_started_at,
                plan_version=plan_version,
                decision=decision,
            )

    def _process_locked(
        self,
        trigger: DecisionTriggerEvidence,
        *,
        recorded_at: datetime,
        cycle_started_at: datetime | None,
        plan_version: ContinuousPlanVersion | None,
        decision: ContinuousPlanDecision | None,
    ) -> EventDecisionCycleResult:
        validate_trigger(trigger)
        recorded = _aware(recorded_at, "Trigger processing timestamp")
        if recorded < _timestamp(trigger.receipt_timestamp, "Trigger receipt timestamp"):
            raise EventDecisionCycleError(
                "Trigger processing timestamp predates receipt evidence."
            )
        ledger = self.store.load()
        existing = next(
            (item for item in ledger.receipts if item.trigger.trigger_id == trigger.trigger_id),
            None,
        )
        if existing is not None:
            self._validate_duplicate_request(
                existing,
                trigger=trigger,
                plan_version=plan_version,
                decision=decision,
            )
            cycle = next(
                (item for item in ledger.cycles if item.cycle_id == existing.cycle_id),
                None,
            )
            return EventDecisionCycleResult(DUPLICATE, existing, cycle)

        if trigger.trigger_type != QUOTE_UPDATE and (
            trigger.trigger_type not in self.policy.allowed_trigger_types
        ):
            raise EventDecisionCycleError(
                "Decision trigger is not enabled by the frozen policy."
            )

        predecessor = _latest_cycle(ledger, trigger.opportunity_id)
        disposition, reasons = self._disposition(trigger, predecessor)
        cycle: EventDrivenDecisionCycle | None = None
        if disposition == CYCLE_CREATED:
            if plan_version is None or decision is None or cycle_started_at is None:
                raise EventDecisionCycleError(
                    "A material decision cycle requires plan, decision, and start evidence."
                )
            cycle = _build_cycle(
                trigger=trigger,
                plan_version=plan_version,
                decision=decision,
                cycle_started_at=cycle_started_at,
                policy=self.policy,
                predecessor=predecessor,
            )
            if recorded < _timestamp(cycle.decided_at, "Decision timestamp"):
                raise EventDecisionCycleError(
                    "Trigger processing timestamp predates the completed decision."
                )
        elif any(item is not None for item in (plan_version, decision, cycle_started_at)):
            raise EventDecisionCycleError(
                "A suppressed trigger cannot carry fabricated plan or decision work."
            )

        receipt = _build_receipt(
            sequence=len(ledger.receipts) + 1,
            trigger=trigger,
            policy=self.policy,
            recorded_at=recorded,
            disposition=disposition,
            reasons=reasons,
            plan_version=plan_version,
            decision=decision,
            predecessor=predecessor,
            cycle=cycle,
        )
        updated = EventDecisionCycleLedger(
            receipts=(*ledger.receipts, receipt),
            cycles=(*ledger.cycles, cycle) if cycle is not None else ledger.cycles,
        )
        self.store.save(updated)
        return EventDecisionCycleResult(CREATED, receipt, cycle)

    def _disposition(
        self,
        trigger: DecisionTriggerEvidence,
        predecessor: EventDrivenDecisionCycle | None,
    ) -> tuple[str, tuple[str, ...]]:
        if trigger.quote_only:
            return QUOTE_ONLY_IGNORED, ("QUOTE_ONLY_EVENT_DOES_NOT_CREATE_CYCLE",)
        if trigger.materiality != MATERIAL:
            return INSUFFICIENT_DELTA_IGNORED, (
                "MINIMUM_EVIDENCE_DELTA_NOT_MET",
            )
        if predecessor is not None and not _is_safety_trigger(trigger):
            cooldown_ends = _timestamp(
                predecessor.decided_at, "Predecessor decision timestamp"
            ) + timedelta(seconds=self.policy.cooldown_seconds)
            if _timestamp(trigger.occurred_at, "Trigger occurrence timestamp") < cooldown_ends:
                return COOLDOWN_SUPPRESSED, (
                    "OPPORTUNITY_COOLDOWN_ACTIVE",
                    f"COOLDOWN_ENDS_AT:{cooldown_ends.isoformat()}",
                )
        return CYCLE_CREATED, ()

    def _validate_duplicate_request(
        self,
        existing: DecisionTriggerReceipt,
        *,
        trigger: DecisionTriggerEvidence,
        plan_version: ContinuousPlanVersion | None,
        decision: ContinuousPlanDecision | None,
    ) -> None:
        if existing.trigger != trigger or existing.policy.fingerprint != self.policy.fingerprint:
            raise EventDecisionCycleError(
                "Decision trigger identity was reused with conflicting evidence."
            )
        expected_plan_id = plan_version.plan_version_id if plan_version else ""
        expected_plan_fingerprint = plan_version.fingerprint if plan_version else ""
        expected_decision_id = decision.decision_id if decision else ""
        expected_decision_fingerprint = decision.fingerprint if decision else ""
        if (
            existing.plan_version_id,
            existing.plan_version_fingerprint,
            existing.continuous_decision_id,
            existing.continuous_decision_fingerprint,
        ) != (
            expected_plan_id,
            expected_plan_fingerprint,
            expected_decision_id,
            expected_decision_fingerprint,
        ):
            raise EventDecisionCycleError(
                "Decision trigger replay contradicts its original plan or decision."
            )


def _build_cycle(
    *,
    trigger: DecisionTriggerEvidence,
    plan_version: ContinuousPlanVersion,
    decision: ContinuousPlanDecision,
    cycle_started_at: datetime,
    policy: EventDecisionCyclePolicy,
    predecessor: EventDrivenDecisionCycle | None,
) -> EventDrivenDecisionCycle:
    validate_plan_version(plan_version)
    validate_decision(decision)
    if policy.configuration_fingerprint != plan_version.configuration_fingerprint:
        raise EventDecisionCycleError(
            "Event-cycle policy configuration does not match the versioned plan."
        )
    _validate_trigger_binding(trigger, plan_version, decision)
    started = _aware(cycle_started_at, "Decision-cycle start timestamp")
    trigger_received = _timestamp(trigger.receipt_timestamp, "Trigger receipt timestamp")
    plan_created = _timestamp(plan_version.created_at, "Plan creation timestamp")
    decided = _timestamp(decision.decided_at, "Decision timestamp")
    if not trigger_received <= started <= plan_created <= decided:
        raise EventDecisionCycleError("Event decision-cycle chronology is invalid.")

    predecessor_id = predecessor.cycle_id if predecessor else ""
    predecessor_fingerprint = predecessor.fingerprint if predecessor else ""
    selection = (
        SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION
        if decision.status == DECISION_AUTHORIZED
        else NO_SELECTION
    )
    core = {
        "sequence": (predecessor.sequence + 1) if predecessor else 1,
        "cycle_started_at": started.isoformat(),
        "decided_at": decision.decided_at,
        "trigger_id": trigger.trigger_id,
        "trigger_fingerprint": trigger.fingerprint,
        "trigger_type": trigger.trigger_type,
        "opportunity_id": trigger.opportunity_id,
        "setup_id": plan_version.setup_id,
        "symbol": trigger.symbol,
        "session_date": trigger.session_date,
        "previous_candidate_state": trigger.previous_candidate_state,
        "next_candidate_state": trigger.next_candidate_state,
        "plan_version_id": plan_version.plan_version_id,
        "plan_version_fingerprint": plan_version.fingerprint,
        "plan_version_number": plan_version.version_number,
        "intraday_plan_id": plan_version.intraday_plan_id,
        "continuous_decision_id": decision.decision_id,
        "continuous_decision_fingerprint": decision.fingerprint,
        "risk_decision_id": decision.risk_decision_id,
        "risk_decision_fingerprint": decision.risk_decision_fingerprint,
        "risk_policy_fingerprint": decision.risk_policy_fingerprint,
        "allocation_decision_cycle_id": decision.allocation_decision_cycle_id,
        "allocation_decision_fingerprint": decision.allocation_decision_fingerprint,
        "allocation_policy_fingerprint": decision.allocation_policy_fingerprint,
        "account_snapshot_fingerprint": decision.account_snapshot_fingerprint,
        "capability_registry_fingerprint": decision.capability_registry_fingerprint,
        "mode": decision.mode,
        "decision_status": decision.status,
        "selection_result": selection,
        "final_authorized_quantity": decision.final_authorized_quantity,
        "blockers": decision.blockers,
        "predecessor_cycle_id": predecessor_id,
        "predecessor_cycle_fingerprint": predecessor_fingerprint,
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "configuration_fingerprint": policy.configuration_fingerprint,
        "schema_version": EVENT_DECISION_SCHEMA_VERSION,
        "profile": EVENT_DECISION_PROFILE,
    }
    identity = fingerprint_payload(
        {
            "trigger_id": trigger.trigger_id,
            "plan_version_id": plan_version.plan_version_id,
            "continuous_decision_fingerprint": decision.fingerprint,
        }
    )
    provisional = EventDrivenDecisionCycle(
        cycle_id=f"event-cycle-{identity[:24]}",
        fingerprint="",
        **core,
    )
    cycle = replace(provisional, fingerprint=cycle_fingerprint(provisional))
    validate_cycle(cycle)
    return cycle


def _build_receipt(
    *,
    sequence: int,
    trigger: DecisionTriggerEvidence,
    policy: EventDecisionCyclePolicy,
    recorded_at: datetime,
    disposition: str,
    reasons: tuple[str, ...],
    plan_version: ContinuousPlanVersion | None,
    decision: ContinuousPlanDecision | None,
    predecessor: EventDrivenDecisionCycle | None,
    cycle: EventDrivenDecisionCycle | None,
) -> DecisionTriggerReceipt:
    core = {
        "sequence": sequence,
        "recorded_at": recorded_at.isoformat(),
        "disposition": disposition,
        "reasons": reasons,
        "trigger": trigger,
        "policy": policy,
        "plan_version_id": plan_version.plan_version_id if plan_version else "",
        "plan_version_fingerprint": plan_version.fingerprint if plan_version else "",
        "continuous_decision_id": decision.decision_id if decision else "",
        "continuous_decision_fingerprint": decision.fingerprint if decision else "",
        "predecessor_cycle_id": predecessor.cycle_id if predecessor else "",
        "cycle_id": cycle.cycle_id if cycle else "",
        "schema_version": EVENT_DECISION_SCHEMA_VERSION,
        "profile": EVENT_DECISION_PROFILE,
    }
    identity = fingerprint_payload(
        {
            "trigger_id": trigger.trigger_id,
            "policy_fingerprint": policy.fingerprint,
            "disposition": disposition,
        }
    )
    provisional = DecisionTriggerReceipt(
        receipt_id=f"decision-receipt-{identity[:24]}",
        fingerprint="",
        **core,
    )
    receipt = replace(provisional, fingerprint=receipt_fingerprint(provisional))
    validate_receipt(receipt)
    return receipt


def _validate_trigger_binding(
    trigger: DecisionTriggerEvidence,
    plan: ContinuousPlanVersion,
    decision: ContinuousPlanDecision,
) -> None:
    if (trigger.opportunity_id, trigger.symbol, trigger.session_date) != (
        plan.opportunity_id,
        plan.symbol,
        plan.session_date,
    ):
        raise EventDecisionCycleError(
            "Decision trigger does not match the versioned plan opportunity."
        )
    if trigger.setup_id and trigger.setup_id != plan.setup_id:
        raise EventDecisionCycleError("Decision trigger setup identity does not match.")
    if trigger.next_candidate_state != plan.candidate_state:
        raise EventDecisionCycleError(
            "Decision trigger candidate state does not match the versioned plan."
        )
    if (
        decision.plan_version_id != plan.plan_version_id
        or decision.plan_version_fingerprint != plan.fingerprint
        or decision.opportunity_id != plan.opportunity_id
        or decision.setup_id != plan.setup_id
        or decision.intraday_plan_id != plan.intraday_plan_id
    ):
        raise EventDecisionCycleError(
            "Continuous decision does not bind the supplied plan version."
        )
    if (
        decision.plan_status != plan.status
        or decision.plan_blockers != plan.blockers
    ):
        raise EventDecisionCycleError(
            "Continuous decision plan authority does not match the supplied plan."
        )
    expected_fingerprints = _trigger_source_fingerprints(trigger.trigger_type, plan)
    if trigger.source_evidence_fingerprint not in expected_fingerprints:
        raise EventDecisionCycleError(
            "Decision trigger source is not frozen by the supplied plan version."
        )
    if trigger.trigger_type in {NEW_CANDIDATE_DISCOVERED, CANDIDATE_STATE_CHANGED} and (
        trigger.candidate_event_id != plan.candidate_event_id
    ):
        raise EventDecisionCycleError(
            "Candidate trigger event does not match the versioned plan."
        )
    if _timestamp(trigger.receipt_timestamp, "Trigger receipt timestamp") > _timestamp(
        plan.created_at, "Plan creation timestamp"
    ):
        raise EventDecisionCycleError("Plan predates its decision trigger evidence.")


def _trigger_source_fingerprints(
    trigger_type: str,
    plan: ContinuousPlanVersion,
) -> frozenset[str]:
    if trigger_type in {NEW_CANDIDATE_DISCOVERED, CANDIDATE_STATE_CHANGED}:
        return frozenset({plan.candidate_evidence_fingerprint})
    if trigger_type in {MEANINGFUL_LEVEL_BREAK, PLAN_MATERIAL_REVISION, PLAN_INVALIDATED}:
        return frozenset(
            {plan.setup_revision_fingerprint, plan.intraday_plan_fingerprint}
        )
    if trigger_type == TIME_NORMALIZED_VOLUME_ABNORMAL:
        return frozenset({plan.rvol_evidence_fingerprint})
    if trigger_type == DIRECT_CATALYST_ARRIVED:
        return frozenset({plan.catalyst_revision_fingerprint})
    if trigger_type in {MARKET_REGIME_CHANGED, SECTOR_REGIME_CHANGED}:
        return frozenset(
            {plan.regime_snapshot_fingerprint, plan.regime_context_fingerprint}
        )
    if trigger_type == EVENT_WINDOW_STABILIZED:
        return frozenset({plan.event_context_fingerprint})
    if trigger_type in {SPREAD_BECAME_EXECUTABLE, DATA_BECAME_STALE}:
        return frozenset(item.evidence_fingerprint for item in plan.source_clocks)
    return frozenset()


def validate_policy(policy: EventDecisionCyclePolicy) -> None:
    _required_text(policy.policy_version, "Event-cycle policy version")
    _sha256(policy.configuration_fingerprint, "Configuration fingerprint")
    _required_text(policy.minimum_delta_profile, "Minimum-delta profile")
    if policy.authority_profile != EVENT_DECISION_AUTHORITY:
        raise EventDecisionCycleError("Event-cycle authority profile is unsupported.")
    if (
        not isinstance(policy.cooldown_seconds, int)
        or isinstance(policy.cooldown_seconds, bool)
        or policy.cooldown_seconds < 0
    ):
        raise EventDecisionCycleError("Event-cycle cooldown must be nonnegative.")
    if policy.quote_only_events_create_cycles:
        raise EventDecisionCycleError("Quote-only events cannot create decision cycles.")
    if (
        not policy.allowed_trigger_types
        or len(set(policy.allowed_trigger_types)) != len(policy.allowed_trigger_types)
        or tuple(sorted(policy.allowed_trigger_types)) != policy.allowed_trigger_types
    ):
        raise EventDecisionCycleError(
            "Allowed trigger types must be a nonempty canonical sorted tuple."
        )
    if any(
        item not in TRIGGER_TYPES or item == QUOTE_UPDATE
        for item in policy.allowed_trigger_types
    ):
        raise EventDecisionCycleError(
            "Allowed trigger policy contains an unsupported or quote-only type."
        )


def validate_trigger(trigger: DecisionTriggerEvidence) -> None:
    if trigger.schema_version != EVENT_DECISION_SCHEMA_VERSION or (
        trigger.profile != EVENT_DECISION_PROFILE
    ):
        raise EventDecisionCycleError("Decision trigger schema is unsupported.")
    if trigger.trigger_type not in TRIGGER_TYPES:
        raise EventDecisionCycleError("Decision trigger type is unsupported.")
    if trigger.materiality not in MATERIALITY_STATES:
        raise EventDecisionCycleError("Decision trigger materiality is unsupported.")
    if (trigger.trigger_type == QUOTE_UPDATE) != (trigger.materiality == QUOTE_ONLY):
        raise EventDecisionCycleError("Quote-only trigger identity is contradictory.")
    _sha256(trigger.opportunity_id, "Opportunity identity")
    _optional_sha256(trigger.setup_id, "Setup identity")
    _symbol(trigger.symbol)
    _session_date(trigger.session_date)
    _candidate_state(trigger.previous_candidate_state, allow_empty=True)
    _candidate_state(trigger.next_candidate_state)
    provider = _timestamp(trigger.provider_timestamp, "Trigger provider timestamp")
    occurred = _timestamp(trigger.occurred_at, "Trigger occurrence timestamp")
    received = _timestamp(trigger.receipt_timestamp, "Trigger receipt timestamp")
    if not provider <= occurred <= received:
        raise EventDecisionCycleError("Decision trigger chronology is invalid.")
    _required_text(trigger.source_identity, "Trigger source identity")
    _required_text(trigger.source_evidence_id, "Trigger source evidence identity")
    _sha256(trigger.source_evidence_fingerprint, "Trigger source evidence")
    _required_text(trigger.material_delta_kind, "Trigger material delta")
    _optional_sha256(trigger.candidate_event_id, "Candidate event identity")
    if trigger.trigger_type in {NEW_CANDIDATE_DISCOVERED, CANDIDATE_STATE_CHANGED} and (
        not trigger.candidate_event_id
    ):
        raise EventDecisionCycleError(
            "Candidate-driven trigger lacks a candidate event identity."
        )
    expected = fingerprint_payload(trigger_fingerprint_payload(trigger))
    if trigger.fingerprint != expected or trigger.trigger_id != (
        f"decision-trigger-{expected[:24]}"
    ):
        raise EventDecisionCycleError("Decision trigger fingerprint did not verify.")


def validate_receipt(receipt: DecisionTriggerReceipt) -> None:
    if receipt.schema_version != EVENT_DECISION_SCHEMA_VERSION or (
        receipt.profile != EVENT_DECISION_PROFILE
    ):
        raise EventDecisionCycleError("Decision trigger receipt schema is unsupported.")
    if receipt.sequence <= 0:
        raise EventDecisionCycleError("Decision trigger receipt sequence is invalid.")
    validate_trigger(receipt.trigger)
    validate_policy(receipt.policy)
    recorded = _timestamp(receipt.recorded_at, "Trigger processing timestamp")
    trigger_received = _timestamp(
        receipt.trigger.receipt_timestamp, "Trigger receipt timestamp"
    )
    if recorded < trigger_received:
        raise EventDecisionCycleError(
            "Trigger processing timestamp predates receipt evidence."
        )
    if receipt.disposition not in RECEIPT_DISPOSITIONS:
        raise EventDecisionCycleError("Decision trigger disposition is unsupported.")
    if len(set(receipt.reasons)) != len(receipt.reasons):
        raise EventDecisionCycleError("Decision trigger reasons contain duplicates.")
    if receipt.disposition == CYCLE_CREATED:
        required = (
            receipt.plan_version_id,
            receipt.plan_version_fingerprint,
            receipt.continuous_decision_id,
            receipt.continuous_decision_fingerprint,
            receipt.cycle_id,
        )
        if not all(required) or receipt.reasons:
            raise EventDecisionCycleError("Created-cycle receipt is incomplete.")
        _sha256(receipt.plan_version_fingerprint, "Plan version fingerprint")
        _sha256(
            receipt.continuous_decision_fingerprint,
            "Continuous decision fingerprint",
        )
    elif any(
        (
            receipt.plan_version_id,
            receipt.plan_version_fingerprint,
            receipt.continuous_decision_id,
            receipt.continuous_decision_fingerprint,
            receipt.cycle_id,
        )
    ) or not receipt.reasons:
        raise EventDecisionCycleError("Suppressed trigger receipt is contradictory.")
    expected_identity = fingerprint_payload(
        {
            "trigger_id": receipt.trigger.trigger_id,
            "policy_fingerprint": receipt.policy.fingerprint,
            "disposition": receipt.disposition,
        }
    )
    if receipt.receipt_id != f"decision-receipt-{expected_identity[:24]}":
        raise EventDecisionCycleError("Decision trigger receipt identity is invalid.")
    if receipt.fingerprint != receipt_fingerprint(receipt):
        raise EventDecisionCycleError("Decision trigger receipt fingerprint is invalid.")


def validate_cycle(cycle: EventDrivenDecisionCycle) -> None:
    if cycle.schema_version != EVENT_DECISION_SCHEMA_VERSION or (
        cycle.profile != EVENT_DECISION_PROFILE
    ):
        raise EventDecisionCycleError("Event decision-cycle schema is unsupported.")
    if cycle.sequence <= 0 or cycle.plan_version_number <= 0:
        raise EventDecisionCycleError("Event decision-cycle sequence is invalid.")
    if cycle.trigger_type not in TRIGGER_TYPES or cycle.trigger_type == QUOTE_UPDATE:
        raise EventDecisionCycleError("Event decision-cycle trigger is unsupported.")
    _sha256(cycle.trigger_fingerprint, "Trigger fingerprint")
    _sha256(cycle.opportunity_id, "Opportunity identity")
    _sha256(cycle.setup_id, "Setup identity")
    _symbol(cycle.symbol)
    _session_date(cycle.session_date)
    _candidate_state(cycle.previous_candidate_state, allow_empty=True)
    _candidate_state(cycle.next_candidate_state)
    started = _timestamp(cycle.cycle_started_at, "Decision-cycle start timestamp")
    decided = _timestamp(cycle.decided_at, "Decision timestamp")
    if started > decided:
        raise EventDecisionCycleError("Event decision-cycle chronology is invalid.")
    for value, name in (
        (cycle.plan_version_fingerprint, "Plan version fingerprint"),
        (cycle.continuous_decision_fingerprint, "Continuous decision fingerprint"),
        (cycle.risk_decision_fingerprint, "Risk decision fingerprint"),
        (cycle.risk_policy_fingerprint, "Risk policy fingerprint"),
        (cycle.allocation_decision_fingerprint, "Allocation fingerprint"),
        (cycle.allocation_policy_fingerprint, "Allocation policy fingerprint"),
        (cycle.account_snapshot_fingerprint, "Account snapshot fingerprint"),
        (cycle.capability_registry_fingerprint, "Capability fingerprint"),
        (cycle.policy_fingerprint, "Event-cycle policy fingerprint"),
        (cycle.configuration_fingerprint, "Configuration fingerprint"),
    ):
        _sha256(value, name)
    if cycle.decision_status not in {DECISION_AUTHORIZED, DECISION_NO_TRADE}:
        raise EventDecisionCycleError("Event decision status is unsupported.")
    if cycle.selection_result not in SELECTION_RESULTS:
        raise EventDecisionCycleError("Event selection result is unsupported.")
    if (cycle.decision_status == DECISION_AUTHORIZED) != cycle.selected:
        raise EventDecisionCycleError("Event selection contradicts decision authority.")
    if cycle.selected and cycle.blockers:
        raise EventDecisionCycleError("Selected event cycle contains blockers.")
    if not cycle.selected and not cycle.blockers:
        raise EventDecisionCycleError("No-selection event cycle lacks a reason.")
    if cycle.predecessor_cycle_id:
        _sha256(cycle.predecessor_cycle_fingerprint, "Predecessor cycle fingerprint")
    elif cycle.predecessor_cycle_fingerprint or cycle.sequence != 1:
        raise EventDecisionCycleError("Initial event cycle has predecessor evidence.")
    identity = fingerprint_payload(
        {
            "trigger_id": cycle.trigger_id,
            "plan_version_id": cycle.plan_version_id,
            "continuous_decision_fingerprint": cycle.continuous_decision_fingerprint,
        }
    )
    if cycle.cycle_id != f"event-cycle-{identity[:24]}":
        raise EventDecisionCycleError("Event decision-cycle identity is invalid.")
    if cycle.fingerprint != cycle_fingerprint(cycle):
        raise EventDecisionCycleError("Event decision-cycle fingerprint is invalid.")


def validate_ledger(ledger: EventDecisionCycleLedger) -> None:
    if ledger.schema_version != EVENT_DECISION_SCHEMA_VERSION or (
        ledger.profile != EVENT_DECISION_PROFILE
    ):
        raise EventDecisionCycleError("Event decision-cycle ledger schema is unsupported.")
    seen_triggers: set[str] = set()
    seen_receipts: set[str] = set()
    seen_created_cycles: set[str] = set()
    previous_recorded_at: datetime | None = None
    for sequence, receipt in enumerate(ledger.receipts, start=1):
        validate_receipt(receipt)
        if receipt.sequence != sequence:
            raise EventDecisionCycleError("Decision trigger receipt sequence regressed.")
        if receipt.trigger.trigger_id in seen_triggers or receipt.receipt_id in seen_receipts:
            raise EventDecisionCycleError("Decision trigger receipt identity is duplicated.")
        recorded_at = _timestamp(receipt.recorded_at, "Trigger processing timestamp")
        if previous_recorded_at is not None and recorded_at < previous_recorded_at:
            raise EventDecisionCycleError("Decision trigger receipt chronology regressed.")
        if receipt.disposition == CYCLE_CREATED:
            if receipt.cycle_id in seen_created_cycles:
                raise EventDecisionCycleError(
                    "Created-cycle receipt identity is duplicated."
                )
            seen_created_cycles.add(receipt.cycle_id)
        seen_triggers.add(receipt.trigger.trigger_id)
        seen_receipts.add(receipt.receipt_id)
        previous_recorded_at = recorded_at

    cycles_by_id: dict[str, EventDrivenDecisionCycle] = {}
    latest_by_opportunity: dict[str, EventDrivenDecisionCycle] = {}
    sequence_by_opportunity: dict[str, int] = {}
    for cycle in ledger.cycles:
        validate_cycle(cycle)
        if cycle.cycle_id in cycles_by_id:
            raise EventDecisionCycleError("Event decision-cycle identity is duplicated.")
        expected_sequence = sequence_by_opportunity.get(cycle.opportunity_id, 0) + 1
        if cycle.sequence != expected_sequence:
            raise EventDecisionCycleError("Opportunity decision-cycle sequence regressed.")
        predecessor = latest_by_opportunity.get(cycle.opportunity_id)
        if predecessor is None:
            if cycle.predecessor_cycle_id or cycle.predecessor_cycle_fingerprint:
                raise EventDecisionCycleError("Initial opportunity cycle has a predecessor.")
        elif (
            cycle.predecessor_cycle_id,
            cycle.predecessor_cycle_fingerprint,
        ) != (predecessor.cycle_id, predecessor.fingerprint):
            raise EventDecisionCycleError("Event decision-cycle predecessor is contradictory.")
        if predecessor is not None and _timestamp(
            cycle.cycle_started_at, "Decision-cycle start timestamp"
        ) < _timestamp(predecessor.decided_at, "Predecessor decision timestamp"):
            raise EventDecisionCycleError(
                "Event decision-cycle chronology predates its predecessor."
            )
        cycles_by_id[cycle.cycle_id] = cycle
        latest_by_opportunity[cycle.opportunity_id] = cycle
        sequence_by_opportunity[cycle.opportunity_id] = cycle.sequence

    created_receipts = {
        item.cycle_id: item
        for item in ledger.receipts
        if item.disposition == CYCLE_CREATED
    }
    if set(created_receipts) != set(cycles_by_id):
        raise EventDecisionCycleError("Cycle receipts and event cycles are inconsistent.")
    for cycle_id, cycle in cycles_by_id.items():
        receipt = created_receipts[cycle_id]
        if (
            receipt.policy.policy_version,
            receipt.policy.fingerprint,
            receipt.policy.configuration_fingerprint,
            receipt.predecessor_cycle_id,
        ) != (
            cycle.policy_version,
            cycle.policy_fingerprint,
            cycle.configuration_fingerprint,
            cycle.predecessor_cycle_id,
        ):
            raise EventDecisionCycleError(
                "Cycle receipt policy or predecessor binding is contradictory."
            )
        if (
            receipt.trigger.trigger_id,
            receipt.trigger.fingerprint,
            receipt.trigger.trigger_type,
            receipt.trigger.opportunity_id,
            receipt.trigger.symbol,
            receipt.trigger.session_date,
            receipt.trigger.previous_candidate_state,
            receipt.trigger.next_candidate_state,
            receipt.plan_version_id,
            receipt.plan_version_fingerprint,
            receipt.continuous_decision_id,
            receipt.continuous_decision_fingerprint,
        ) != (
            cycle.trigger_id,
            cycle.trigger_fingerprint,
            cycle.trigger_type,
            cycle.opportunity_id,
            cycle.symbol,
            cycle.session_date,
            cycle.previous_candidate_state,
            cycle.next_candidate_state,
            cycle.plan_version_id,
            cycle.plan_version_fingerprint,
            cycle.continuous_decision_id,
            cycle.continuous_decision_fingerprint,
        ):
            raise EventDecisionCycleError("Cycle receipt source binding is contradictory.")
        if receipt.trigger.setup_id and receipt.trigger.setup_id != cycle.setup_id:
            raise EventDecisionCycleError("Cycle receipt setup binding is contradictory.")
        trigger_received = _timestamp(
            receipt.trigger.receipt_timestamp, "Trigger receipt timestamp"
        )
        cycle_started = _timestamp(
            cycle.cycle_started_at, "Decision-cycle start timestamp"
        )
        decided_at = _timestamp(cycle.decided_at, "Decision timestamp")
        recorded_at = _timestamp(receipt.recorded_at, "Trigger processing timestamp")
        if not trigger_received <= cycle_started <= decided_at <= recorded_at:
            raise EventDecisionCycleError(
                "Cycle receipt chronology is contradictory."
            )


def _is_safety_trigger(trigger: DecisionTriggerEvidence) -> bool:
    return trigger.trigger_type in SAFETY_TRIGGER_TYPES or (
        trigger.trigger_type == CANDIDATE_STATE_CHANGED
        and trigger.next_candidate_state in SAFETY_CANDIDATE_STATES
    )


def _latest_cycle(
    ledger: EventDecisionCycleLedger,
    opportunity_id: str,
) -> EventDrivenDecisionCycle | None:
    return next(
        (
            item
            for item in reversed(ledger.cycles)
            if item.opportunity_id == opportunity_id
        ),
        None,
    )


def trigger_fingerprint_payload(trigger: DecisionTriggerEvidence) -> dict[str, object]:
    payload = asdict(trigger)
    payload.pop("trigger_id", None)
    payload.pop("fingerprint", None)
    return payload


def receipt_fingerprint(receipt: DecisionTriggerReceipt) -> str:
    return fingerprint_payload(asdict(replace(receipt, fingerprint="")))


def cycle_fingerprint(cycle: EventDrivenDecisionCycle) -> str:
    return fingerprint_payload(asdict(replace(cycle, fingerprint="")))


def ledger_to_wire(ledger: EventDecisionCycleLedger) -> dict[str, object]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "receipts": [asdict(item) for item in ledger.receipts],
        "cycles": [asdict(item) for item in ledger.cycles],
    }


def ledger_from_wire(payload: object) -> EventDecisionCycleLedger:
    if not isinstance(payload, Mapping):
        raise EventDecisionCycleError("Event decision-cycle ledger has an invalid shape.")
    receipts = payload.get("receipts")
    cycles = payload.get("cycles")
    if not isinstance(receipts, list) or not isinstance(cycles, list):
        raise EventDecisionCycleError("Event decision-cycle ledger has an invalid schema.")
    try:
        parsed_receipts = []
        for item in receipts:
            if not isinstance(item, Mapping):
                raise TypeError("Malformed receipt")
            values = dict(item)
            trigger = values.get("trigger")
            policy = values.get("policy")
            if not isinstance(trigger, Mapping) or not isinstance(policy, Mapping):
                raise TypeError("Malformed nested receipt evidence")
            values["trigger"] = DecisionTriggerEvidence(**dict(trigger))
            policy_values = dict(policy)
            policy_values["allowed_trigger_types"] = tuple(
                policy_values.get("allowed_trigger_types", ())
            )
            values["policy"] = EventDecisionCyclePolicy(**policy_values)
            values["reasons"] = tuple(values.get("reasons", ()))
            parsed_receipts.append(DecisionTriggerReceipt(**values))
        parsed_cycles = []
        for item in cycles:
            if not isinstance(item, Mapping):
                raise TypeError("Malformed cycle")
            values = dict(item)
            values["blockers"] = tuple(values.get("blockers", ()))
            parsed_cycles.append(EventDrivenDecisionCycle(**values))
        ledger = EventDecisionCycleLedger(
            schema_version=int(payload.get("schema_version", 0)),
            profile=str(payload.get("profile", "")),
            receipts=tuple(parsed_receipts),
            cycles=tuple(parsed_cycles),
        )
    except (TypeError, ValueError) as exc:
        raise EventDecisionCycleError(
            "Event decision-cycle ledger contains an invalid record."
        ) from exc
    return ledger


def fingerprint_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[resolved] = lock
        return lock


def _lease_depths() -> dict[Path, int]:
    depths = getattr(_PATH_LEASE_STATE, "depths", None)
    if depths is None:
        depths = {}
        _PATH_LEASE_STATE.depths = depths
    return depths


@contextmanager
def _exclusive_path_lease(
    path: Path,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    last_error: OSError | None = None
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        while not acquired:
            try:
                _lock_file_handle(handle)
                acquired = True
            except OSError as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EventDecisionCycleError(
                        "Event decision-cycle ledger lease timed out."
                    ) from last_error
                time.sleep(min(0.01, remaining))
        try:
            yield
        finally:
            if acquired:
                _unlock_file_handle(handle)


def _lock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _required_text(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise EventDecisionCycleError(f"{name} is required.")
    return text


def _sha256(value: object, name: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256.fullmatch(text):
        raise EventDecisionCycleError(f"{name} fingerprint is invalid.")
    return text


def _optional_sha256(value: object, name: str) -> str:
    text = str(value).strip().lower()
    return _sha256(text, name) if text else ""


def _symbol(value: object) -> str:
    symbol = str(value).strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise EventDecisionCycleError("Decision trigger symbol is invalid.")
    return symbol


def _session_date(value: object) -> str:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError as exc:
        raise EventDecisionCycleError("Decision trigger session date is invalid.") from exc
    return parsed.date().isoformat()


def _candidate_state(value: object, *, allow_empty: bool = False) -> str:
    state = str(value).strip().upper()
    if allow_empty and not state:
        return ""
    if state not in CANDIDATE_STATES:
        raise EventDecisionCycleError("Decision trigger candidate state is unsupported.")
    return state


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventDecisionCycleError(f"{name} must include a UTC offset.")
    return value


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventDecisionCycleError(f"{name} is invalid.") from exc
    return _aware(parsed, name)
