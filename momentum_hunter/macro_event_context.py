"""Versioned offline macro-event calendar and risk-context adjudication.

This module evaluates caller-supplied event windows under a caller-supplied
policy. It does not fetch calendars, choose production windows, score
candidates, initiate trades, or contact a provider or broker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


EVENT_SCHEMA_VERSION = 1
EVENT_PROFILE = "versioned-macro-event-context-v1"
MAX_CALENDAR_EVENTS = 1_000

NORMAL = "NORMAL"
CAUTION = "CAUTION"
BLOCK_NEW_ENTRY = "BLOCK_NEW_ENTRY"
DATA_STALE = "DATA_STALE"
EVENT_CONTEXT_STATES = frozenset({NORMAL, CAUTION, BLOCK_NEW_ENTRY, DATA_STALE})
_CONTEXT_PRIORITY = {NORMAL: 0, CAUTION: 1, BLOCK_NEW_ENTRY: 2, DATA_STALE: 3}

FED_DECISION = "FED_DECISION"
FED_SPEAKER = "FED_SPEAKER"
INFLATION_RELEASE = "INFLATION_RELEASE"
JOBS_REPORT = "JOBS_REPORT"
TREASURY_AUCTION = "TREASURY_AUCTION"
COMPANY_EARNINGS = "COMPANY_EARNINGS"
MARKET_HOLIDAY = "MARKET_HOLIDAY"
EARLY_CLOSE = "EARLY_CLOSE"
APPROVED_OTHER = "APPROVED_OTHER"
EVENT_CATEGORIES = frozenset(
    {
        FED_DECISION,
        FED_SPEAKER,
        INFLATION_RELEASE,
        JOBS_REPORT,
        TREASURY_AUCTION,
        COMPANY_EARNINGS,
        MARKET_HOLIDAY,
        EARLY_CLOSE,
        APPROVED_OTHER,
    }
)

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
CRITICAL = "CRITICAL"
IMPORTANCE_LEVELS = (LOW, MEDIUM, HIGH, CRITICAL)
_IMPORTANCE_RANK = {value: index for index, value in enumerate(IMPORTANCE_LEVELS)}

CURRENT = "CURRENT"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
CANCELLED = "CANCELLED"
EVENT_EVIDENCE_STATES = frozenset({CURRENT, STALE, UNKNOWN, CANCELLED})

MARKET = "MARKET"
SECTOR = "SECTOR"
SYMBOL = "SYMBOL"
EVENT_SCOPES = frozenset({MARKET, SECTOR, SYMBOL})

NO_SCORE_AUTHORITY = "NONE"

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class MacroEventContextError(ValueError):
    """Raised when calendar evidence or policy is ambiguous or contradictory."""


@dataclass(frozen=True)
class EventDefinition:
    source_event_id: str
    revision_identity: str
    category: str
    title: str
    importance: str
    evidence_state: str
    scheduled_start: str
    scheduled_end: str
    risk_window_start: str
    risk_window_end: str
    observation_window_start: str
    observation_window_end: str
    scope: str
    source_identity: str
    provider_timestamp: str
    receipt_timestamp: str
    affected_symbols: tuple[str, ...] = field(default_factory=tuple)
    affected_sector_symbols: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    source_event_id: str
    revision_identity: str
    category: str
    title: str
    importance: str
    evidence_state: str
    scheduled_start: str
    scheduled_end: str
    risk_window_start: str
    risk_window_end: str
    observation_window_start: str
    observation_window_end: str
    scope: str
    source_identity: str
    provider_timestamp: str
    receipt_timestamp: str
    affected_symbols: tuple[str, ...]
    affected_sector_symbols: tuple[str, ...]
    notes: str
    fingerprint: str


@dataclass(frozen=True)
class EventConsequenceRule:
    category: str
    minimum_importance: str
    context: str


@dataclass(frozen=True)
class EventRiskPolicy:
    policy_version: str
    rules: tuple[EventConsequenceRule, ...]
    maximum_candidate_fan_out: int
    unknown_or_stale_event_context: str = DATA_STALE
    missing_rule_context: str = DATA_STALE

    @property
    def fingerprint(self) -> str:
        return fingerprint_payload(asdict(self))


@dataclass(frozen=True)
class EventCalendarSnapshot:
    sequence: int
    calendar_id: str
    generated_at: str
    valid_through: str
    previous_calendar_id: str
    source_identities: tuple[str, ...]
    events: tuple[CalendarEvent, ...]
    fingerprint: str
    schema_version: int = EVENT_SCHEMA_VERSION
    profile: str = EVENT_PROFILE


@dataclass(frozen=True)
class EventCalendarLedger:
    snapshots: tuple[EventCalendarSnapshot, ...] = field(default_factory=tuple)
    schema_version: int = EVENT_SCHEMA_VERSION
    profile: str = EVENT_PROFILE


@dataclass(frozen=True)
class EventRiskTarget:
    opportunity_id: str
    symbol: str
    sector_symbol: str = ""


@dataclass(frozen=True)
class EventRiskContext:
    context_id: str
    evaluated_at: str
    status: str
    reason: str
    calendar_id: str
    calendar_fingerprint: str
    policy: EventRiskPolicy
    policy_version: str
    policy_fingerprint: str
    target_opportunity_id: str
    target_symbol: str
    target_sector_symbol: str
    active_event_ids: tuple[str, ...]
    active_event_revisions: tuple[str, ...]
    score_authority: str
    can_initiate_trade: bool
    fingerprint: str
    schema_version: int = EVENT_SCHEMA_VERSION
    profile: str = EVENT_PROFILE


class EventCalendarStore:
    """Atomic append-only snapshot chain for event-calendar revisions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> EventCalendarLedger:
        with self._lock:
            if not self.path.exists():
                return EventCalendarLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise MacroEventContextError(
                    f"Event calendar evidence cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def append(self, snapshot: EventCalendarSnapshot) -> EventCalendarSnapshot:
        with self._lock:
            ledger = self.load()
            existing = next(
                (
                    item
                    for item in ledger.snapshots
                    if item.calendar_id == snapshot.calendar_id
                ),
                None,
            )
            if existing is not None:
                if existing != snapshot:
                    raise MacroEventContextError(
                        "Calendar identity was reused with conflicting evidence."
                    )
                return existing
            previous = ledger.snapshots[-1] if ledger.snapshots else None
            if snapshot.sequence != len(ledger.snapshots) + 1:
                raise MacroEventContextError(
                    "Calendar snapshot sequence was not append-only."
                )
            expected_previous = previous.calendar_id if previous else ""
            if snapshot.previous_calendar_id != expected_previous:
                raise MacroEventContextError(
                    "Calendar snapshot did not extend the current chain."
                )
            if previous and _timestamp(
                snapshot.generated_at, "Calendar generation timestamp"
            ) <= _timestamp(
                previous.generated_at, "Previous calendar generation timestamp"
            ):
                raise MacroEventContextError(
                    "Calendar snapshot chronology was not strictly increasing."
                )
            validate_calendar(snapshot)
            updated = replace(
                ledger,
                snapshots=(*ledger.snapshots, snapshot),
            )
            validate_ledger(updated)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(updated)))
            return snapshot


def build_event_calendar(
    *,
    definitions: Sequence[EventDefinition],
    generated_at: datetime,
    valid_through: datetime,
    previous_snapshot: EventCalendarSnapshot | None = None,
    sequence: int | None = None,
) -> EventCalendarSnapshot:
    """Normalize a source calendar into one immutable deterministic snapshot."""

    generated = _aware(generated_at, "Calendar generation timestamp")
    valid = _aware(valid_through, "Calendar valid-through timestamp")
    if valid <= generated:
        raise MacroEventContextError(
            "Calendar valid-through timestamp must follow generation."
        )
    if previous_snapshot and generated <= _timestamp(
        previous_snapshot.generated_at, "Previous calendar generation timestamp"
    ):
        raise MacroEventContextError(
            "Calendar snapshot chronology must be strictly increasing."
        )
    if len(definitions) > MAX_CALENDAR_EVENTS:
        raise MacroEventContextError("Calendar exceeded the bounded event limit.")

    events = tuple(
        sorted(
            (_calendar_event(item, generated) for item in definitions),
            key=lambda item: (item.scheduled_start, item.event_id),
        )
    )
    if len({item.event_id for item in events}) != len(events):
        raise MacroEventContextError(
            "Calendar repeated a source event identity in one snapshot."
        )
    if previous_snapshot:
        _validate_revisions(previous_snapshot.events, events)
    expected_sequence = (
        previous_snapshot.sequence + 1 if previous_snapshot else 1
    )
    if sequence is not None and sequence != expected_sequence:
        raise MacroEventContextError(
            "Calendar snapshot sequence did not extend its predecessor."
        )
    next_sequence = expected_sequence
    payload = {
        "sequence": next_sequence,
        "generated_at": generated.isoformat(),
        "valid_through": valid.isoformat(),
        "previous_calendar_id": (
            previous_snapshot.calendar_id if previous_snapshot else ""
        ),
        "source_identities": tuple(
            sorted({item.source_identity for item in events})
        ),
        "events": tuple(asdict(item) for item in events),
        "schema_version": EVENT_SCHEMA_VERSION,
        "profile": EVENT_PROFILE,
    }
    fingerprint = fingerprint_payload(payload)
    snapshot = EventCalendarSnapshot(
        calendar_id=f"calendar-{fingerprint[:24]}",
        fingerprint=fingerprint,
        events=events,
        **{key: value for key, value in payload.items() if key != "events"},
    )
    validate_calendar(snapshot)
    return snapshot


def evaluate_event_risk(
    *,
    calendar: EventCalendarSnapshot,
    policy: EventRiskPolicy,
    evaluated_at: datetime,
    target: EventRiskTarget | None = None,
) -> EventRiskContext:
    """Evaluate one market-wide or candidate-specific event context."""

    validate_calendar(calendar)
    validate_policy(policy)
    evaluated = _aware(evaluated_at, "Event-context evaluation timestamp")
    generated = _timestamp(calendar.generated_at, "Calendar generation timestamp")
    target_value = _normalize_target(target)
    if evaluated < generated:
        raise MacroEventContextError(
            "Event context cannot use a calendar generated in the future."
        )

    matching = tuple(
        item
        for item in calendar.events
        if _event_applies(item, target_value)
        and _timestamp(item.risk_window_start, "Risk window start")
        <= evaluated
        <= _timestamp(item.risk_window_end, "Risk window end")
    )
    active = tuple(item for item in matching if item.evidence_state != CANCELLED)
    if evaluated > _timestamp(calendar.valid_through, "Calendar valid-through"):
        status = DATA_STALE
        reason = "CALENDAR_VALIDITY_EXPIRED"
    else:
        unsafe = tuple(
            item for item in active if item.evidence_state in {STALE, UNKNOWN}
        )
        if unsafe:
            status = policy.unknown_or_stale_event_context
            reason = "ACTIVE_EVENT_EVIDENCE_UNSAFE"
        else:
            consequences: list[tuple[str, CalendarEvent]] = []
            missing_rules: list[CalendarEvent] = []
            for event in active:
                context = _rule_context(event, policy)
                if context is None:
                    missing_rules.append(event)
                else:
                    consequences.append((context, event))
            if missing_rules:
                status = policy.missing_rule_context
                reason = "ACTIVE_EVENT_POLICY_RULE_MISSING"
            elif consequences:
                status = max(
                    (item[0] for item in consequences),
                    key=lambda value: _CONTEXT_PRIORITY[value],
                )
                reason = "ACTIVE_EVENT_POLICY_APPLIED"
            else:
                status = NORMAL
                reason = "NO_ACTIVE_APPLICABLE_EVENT"

    context_payload = {
        "evaluated_at": evaluated.isoformat(),
        "status": status,
        "reason": reason,
        "calendar_id": calendar.calendar_id,
        "calendar_fingerprint": calendar.fingerprint,
        "policy": asdict(policy),
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "target_opportunity_id": target_value.opportunity_id if target_value else "",
        "target_symbol": target_value.symbol if target_value else "",
        "target_sector_symbol": target_value.sector_symbol if target_value else "",
        "active_event_ids": tuple(item.event_id for item in active),
        "active_event_revisions": tuple(item.revision_identity for item in active),
        "score_authority": NO_SCORE_AUTHORITY,
        "can_initiate_trade": False,
        "schema_version": EVENT_SCHEMA_VERSION,
        "profile": EVENT_PROFILE,
    }
    fingerprint = fingerprint_payload(context_payload)
    context = EventRiskContext(
        context_id=f"event-context-{fingerprint[:24]}",
        fingerprint=fingerprint,
        policy=policy,
        **{
            key: value
            for key, value in context_payload.items()
            if key != "policy"
        },
    )
    validate_context(context)
    return context


def fan_out_event_risk(
    *,
    calendar: EventCalendarSnapshot,
    policy: EventRiskPolicy,
    evaluated_at: datetime,
    targets: Sequence[EventRiskTarget],
) -> tuple[EventRiskContext, ...]:
    """Evaluate a bounded ordered watched-candidate set."""

    validate_policy(policy)
    if len(targets) > policy.maximum_candidate_fan_out:
        raise MacroEventContextError(
            "Event context fan-out exceeded the bounded candidate limit."
        )
    normalized = tuple(_normalize_target(item) for item in targets)
    opportunity_ids = [item.opportunity_id for item in normalized if item]
    if len(set(opportunity_ids)) != len(opportunity_ids):
        raise MacroEventContextError(
            "Event context fan-out repeated an opportunity identity."
        )
    return tuple(
        evaluate_event_risk(
            calendar=calendar,
            policy=policy,
            evaluated_at=evaluated_at,
            target=item,
        )
        for item in normalized
        if item is not None
    )


def expected_event_id(source_identity: str, source_event_id: str) -> str:
    source = _identity(source_identity, "Event source identity")
    event = _identity(source_event_id, "Source event identity")
    return f"event-{fingerprint_payload({'source': source, 'event': event})[:24]}"


def validate_policy(policy: EventRiskPolicy) -> None:
    _identity(policy.policy_version, "Event-risk policy version")
    if (
        isinstance(policy.maximum_candidate_fan_out, bool)
        or not isinstance(policy.maximum_candidate_fan_out, int)
        or policy.maximum_candidate_fan_out <= 0
    ):
        raise MacroEventContextError(
            "Event-risk fan-out limit must be a positive integer."
        )
    if policy.unknown_or_stale_event_context != DATA_STALE:
        raise MacroEventContextError(
            "Unsafe event evidence must fail closed as DATA_STALE."
        )
    if policy.missing_rule_context != DATA_STALE:
        raise MacroEventContextError(
            "Missing event policy rules must fail closed as DATA_STALE."
        )
    seen: set[tuple[str, str]] = set()
    for rule in policy.rules:
        if rule.category not in EVENT_CATEGORIES:
            raise MacroEventContextError("Event policy category was unsupported.")
        if rule.minimum_importance not in _IMPORTANCE_RANK:
            raise MacroEventContextError("Event policy importance was unsupported.")
        if rule.context not in {CAUTION, BLOCK_NEW_ENTRY}:
            raise MacroEventContextError(
                "Active event policy may only caution or block new entry."
            )
        identity = (rule.category, rule.minimum_importance)
        if identity in seen:
            raise MacroEventContextError("Event policy repeated a rule identity.")
        seen.add(identity)


def validate_calendar(snapshot: EventCalendarSnapshot) -> None:
    if snapshot.schema_version != EVENT_SCHEMA_VERSION or snapshot.profile != EVENT_PROFILE:
        raise MacroEventContextError("Calendar schema identity was unsupported.")
    if snapshot.sequence <= 0:
        raise MacroEventContextError("Calendar sequence was invalid.")
    generated = _timestamp(snapshot.generated_at, "Calendar generation timestamp")
    valid = _timestamp(snapshot.valid_through, "Calendar valid-through timestamp")
    if valid <= generated:
        raise MacroEventContextError("Calendar validity window was invalid.")
    if len(snapshot.events) > MAX_CALENDAR_EVENTS:
        raise MacroEventContextError("Calendar exceeded the bounded event limit.")
    for event in snapshot.events:
        validate_event(event, generated_at=generated)
    if len({item.event_id for item in snapshot.events}) != len(snapshot.events):
        raise MacroEventContextError("Calendar repeated an event identity.")
    if tuple(sorted({item.source_identity for item in snapshot.events})) != snapshot.source_identities:
        raise MacroEventContextError("Calendar source identities did not verify.")
    if not _SHA256.fullmatch(snapshot.fingerprint):
        raise MacroEventContextError("Calendar fingerprint was invalid.")
    if fingerprint_payload(calendar_fingerprint_payload(snapshot)) != snapshot.fingerprint:
        raise MacroEventContextError("Calendar fingerprint did not verify.")
    if snapshot.calendar_id != f"calendar-{snapshot.fingerprint[:24]}":
        raise MacroEventContextError("Calendar identity did not verify.")


def validate_event(event: CalendarEvent, *, generated_at: datetime) -> None:
    if event.event_id != expected_event_id(event.source_identity, event.source_event_id):
        raise MacroEventContextError("Calendar event identity did not verify.")
    _identity(event.revision_identity, "Event revision identity")
    _required_text(event.title, "Event title")
    if event.category not in EVENT_CATEGORIES:
        raise MacroEventContextError("Calendar event category was unsupported.")
    if event.importance not in _IMPORTANCE_RANK:
        raise MacroEventContextError("Calendar event importance was unsupported.")
    if event.evidence_state not in EVENT_EVIDENCE_STATES:
        raise MacroEventContextError("Calendar event evidence state was unsupported.")
    if event.scope not in EVENT_SCOPES:
        raise MacroEventContextError("Calendar event scope was unsupported.")
    _validate_scope(event.scope, event.affected_symbols, event.affected_sector_symbols)
    provider = _timestamp(event.provider_timestamp, "Event provider timestamp")
    receipt = _timestamp(event.receipt_timestamp, "Event receipt timestamp")
    if provider > receipt or receipt > generated_at:
        raise MacroEventContextError("Event source chronology was invalid.")
    observation_start = _timestamp(
        event.observation_window_start, "Observation window start"
    )
    risk_start = _timestamp(event.risk_window_start, "Risk window start")
    scheduled_start = _timestamp(event.scheduled_start, "Scheduled event start")
    scheduled_end = _timestamp(event.scheduled_end, "Scheduled event end")
    risk_end = _timestamp(event.risk_window_end, "Risk window end")
    observation_end = _timestamp(
        event.observation_window_end, "Observation window end"
    )
    if not (
        observation_start
        <= risk_start
        <= scheduled_start
        <= scheduled_end
        <= risk_end
        <= observation_end
    ):
        raise MacroEventContextError("Event windows were contradictory.")
    if not _SHA256.fullmatch(event.fingerprint):
        raise MacroEventContextError("Calendar event fingerprint was invalid.")
    if fingerprint_payload(event_fingerprint_payload(event)) != event.fingerprint:
        raise MacroEventContextError("Calendar event fingerprint did not verify.")


def validate_context(context: EventRiskContext) -> None:
    if context.status not in EVENT_CONTEXT_STATES:
        raise MacroEventContextError("Event context status was unsupported.")
    if context.score_authority != NO_SCORE_AUTHORITY or context.can_initiate_trade:
        raise MacroEventContextError("Event context claimed trading authority.")
    validate_policy(context.policy)
    if (
        context.policy_version != context.policy.policy_version
        or context.policy_fingerprint != context.policy.fingerprint
    ):
        raise MacroEventContextError("Event context policy identity did not verify.")
    if context.schema_version != EVENT_SCHEMA_VERSION or context.profile != EVENT_PROFILE:
        raise MacroEventContextError("Event context schema identity was unsupported.")
    if not _SHA256.fullmatch(context.fingerprint):
        raise MacroEventContextError("Event context fingerprint was invalid.")
    if fingerprint_payload(context_fingerprint_payload(context)) != context.fingerprint:
        raise MacroEventContextError("Event context fingerprint did not verify.")
    if context.context_id != f"event-context-{context.fingerprint[:24]}":
        raise MacroEventContextError("Event context identity did not verify.")


def validate_ledger(ledger: EventCalendarLedger) -> None:
    if ledger.schema_version != EVENT_SCHEMA_VERSION or ledger.profile != EVENT_PROFILE:
        raise MacroEventContextError("Calendar ledger schema identity was unsupported.")
    previous: EventCalendarSnapshot | None = None
    seen: set[str] = set()
    for sequence, snapshot in enumerate(ledger.snapshots, start=1):
        validate_calendar(snapshot)
        if snapshot.sequence != sequence:
            raise MacroEventContextError("Calendar ledger sequence was invalid.")
        if snapshot.calendar_id in seen:
            raise MacroEventContextError("Calendar ledger repeated an identity.")
        seen.add(snapshot.calendar_id)
        expected_previous = previous.calendar_id if previous else ""
        if snapshot.previous_calendar_id != expected_previous:
            raise MacroEventContextError("Calendar ledger chain was invalid.")
        if previous:
            if _timestamp(
                snapshot.generated_at, "Calendar generation timestamp"
            ) <= _timestamp(
                previous.generated_at, "Previous calendar generation timestamp"
            ):
                raise MacroEventContextError(
                    "Calendar ledger chronology was not strictly increasing."
                )
            _validate_revisions(previous.events, snapshot.events)
        previous = snapshot


def _calendar_event(definition: EventDefinition, generated_at: datetime) -> CalendarEvent:
    source_identity = _identity(definition.source_identity, "Event source identity")
    source_event_id = _identity(definition.source_event_id, "Source event identity")
    event_id = expected_event_id(source_identity, source_event_id)
    payload = {
        "event_id": event_id,
        "source_event_id": source_event_id,
        "revision_identity": _identity(
            definition.revision_identity, "Event revision identity"
        ),
        "category": definition.category,
        "title": _required_text(definition.title, "Event title"),
        "importance": definition.importance,
        "evidence_state": definition.evidence_state,
        "scheduled_start": _iso(_timestamp(definition.scheduled_start, "Scheduled event start")),
        "scheduled_end": _iso(_timestamp(definition.scheduled_end, "Scheduled event end")),
        "risk_window_start": _iso(_timestamp(definition.risk_window_start, "Risk window start")),
        "risk_window_end": _iso(_timestamp(definition.risk_window_end, "Risk window end")),
        "observation_window_start": _iso(_timestamp(definition.observation_window_start, "Observation window start")),
        "observation_window_end": _iso(_timestamp(definition.observation_window_end, "Observation window end")),
        "scope": definition.scope,
        "source_identity": source_identity,
        "provider_timestamp": _iso(_timestamp(definition.provider_timestamp, "Event provider timestamp")),
        "receipt_timestamp": _iso(_timestamp(definition.receipt_timestamp, "Event receipt timestamp")),
        "affected_symbols": _symbols(definition.affected_symbols, "Affected symbol"),
        "affected_sector_symbols": _symbols(
            definition.affected_sector_symbols, "Affected sector symbol"
        ),
        "notes": str(definition.notes or "").strip(),
    }
    fingerprint = fingerprint_payload(payload)
    event = CalendarEvent(fingerprint=fingerprint, **payload)
    validate_event(event, generated_at=generated_at)
    return event


def _validate_revisions(
    previous_events: Sequence[CalendarEvent],
    current_events: Sequence[CalendarEvent],
) -> None:
    previous = {item.event_id: item for item in previous_events}
    for event in current_events:
        old = previous.get(event.event_id)
        if old is None:
            continue
        if old.revision_identity == event.revision_identity and old != event:
            raise MacroEventContextError(
                "Event revision identity was reused with conflicting evidence."
            )


def _rule_context(event: CalendarEvent, policy: EventRiskPolicy) -> str | None:
    matching = [
        rule
        for rule in policy.rules
        if rule.category == event.category
        and _IMPORTANCE_RANK[event.importance]
        >= _IMPORTANCE_RANK[rule.minimum_importance]
    ]
    if not matching:
        return None
    rule = max(
        matching,
        key=lambda item: _IMPORTANCE_RANK[item.minimum_importance],
    )
    return rule.context


def _event_applies(
    event: CalendarEvent,
    target: EventRiskTarget | None,
) -> bool:
    if event.scope == MARKET:
        return True
    if target is None:
        return False
    if event.scope == SYMBOL:
        return target.symbol in event.affected_symbols
    return bool(
        target.sector_symbol
        and target.sector_symbol in event.affected_sector_symbols
    )


def _normalize_target(target: EventRiskTarget | None) -> EventRiskTarget | None:
    if target is None:
        return None
    return EventRiskTarget(
        opportunity_id=_identity(target.opportunity_id, "Opportunity identity"),
        symbol=_symbol(target.symbol, "Target symbol"),
        sector_symbol=(
            _symbol(target.sector_symbol, "Target sector symbol")
            if target.sector_symbol
            else ""
        ),
    )


def _validate_scope(
    scope: str,
    symbols: Sequence[str],
    sectors: Sequence[str],
) -> None:
    normalized_symbols = _symbols(symbols, "Affected symbol")
    normalized_sectors = _symbols(sectors, "Affected sector symbol")
    if scope == MARKET and (normalized_symbols or normalized_sectors):
        raise MacroEventContextError(
            "Market-wide events cannot carry symbol or sector scope."
        )
    if scope == SYMBOL and (not normalized_symbols or normalized_sectors):
        raise MacroEventContextError(
            "Symbol events require only affected symbols."
        )
    if scope == SECTOR and (not normalized_sectors or normalized_symbols):
        raise MacroEventContextError(
            "Sector events require only affected sector symbols."
        )


def calendar_fingerprint_payload(snapshot: EventCalendarSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    payload.pop("calendar_id", None)
    payload.pop("fingerprint", None)
    return payload


def event_fingerprint_payload(event: CalendarEvent) -> dict[str, object]:
    payload = asdict(event)
    payload.pop("fingerprint", None)
    return payload


def context_fingerprint_payload(context: EventRiskContext) -> dict[str, object]:
    payload = asdict(context)
    payload.pop("context_id", None)
    payload.pop("fingerprint", None)
    return payload


def ledger_to_wire(ledger: EventCalendarLedger) -> dict[str, object]:
    return {
        "schemaVersion": ledger.schema_version,
        "profile": ledger.profile,
        "snapshots": [asdict(item) for item in ledger.snapshots],
    }


def ledger_from_wire(payload: object) -> EventCalendarLedger:
    if not isinstance(payload, Mapping):
        raise MacroEventContextError("Calendar ledger root was invalid.")
    if set(payload) != {"schemaVersion", "profile", "snapshots"}:
        raise MacroEventContextError("Calendar ledger fields were unsupported.")
    rows = payload.get("snapshots")
    if not isinstance(rows, list):
        raise MacroEventContextError("Calendar ledger snapshots were invalid.")
    snapshots: list[EventCalendarSnapshot] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise MacroEventContextError("Calendar snapshot row was invalid.")
        body = dict(row)
        raw_events = body.get("events")
        if not isinstance(raw_events, list):
            raise MacroEventContextError("Calendar events were invalid.")
        try:
            events = []
            for raw_event in raw_events:
                event_body = dict(raw_event)
                event_body["affected_symbols"] = tuple(
                    event_body["affected_symbols"]
                )
                event_body["affected_sector_symbols"] = tuple(
                    event_body["affected_sector_symbols"]
                )
                events.append(CalendarEvent(**event_body))
            body["events"] = tuple(events)
            body["source_identities"] = tuple(body["source_identities"])
            snapshots.append(EventCalendarSnapshot(**body))
        except (KeyError, TypeError, ValueError) as exc:
            raise MacroEventContextError(
                "Calendar snapshot fields were invalid."
            ) from exc
    try:
        return EventCalendarLedger(
            snapshots=tuple(snapshots),
            schema_version=int(payload["schemaVersion"]),
            profile=str(payload["profile"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MacroEventContextError("Calendar ledger identity was invalid.") from exc


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


def _identity(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not _IDENTITY.fullmatch(text):
        raise MacroEventContextError(f"{name} was invalid.")
    return text


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MacroEventContextError(f"{name} is required.")
    return text


def _symbol(value: object, name: str) -> str:
    symbol = str(value or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise MacroEventContextError(f"{name} was invalid.")
    return symbol


def _symbols(values: Sequence[str], name: str) -> tuple[str, ...]:
    normalized = tuple(_symbol(value, name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise MacroEventContextError(f"{name} list contained duplicates.")
    return normalized


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacroEventContextError(f"{name} was invalid.") from exc
    return _aware(parsed, name)


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MacroEventContextError(f"{name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
