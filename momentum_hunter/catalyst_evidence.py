"""Immutable provider-neutral catalyst evidence and revision contracts.

This module accepts caller-supplied observations. It does not fetch news,
infer relationships, score candidates, build plans, trigger runtime cycles, or
contact a provider, account, broker, or order surface.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_BLOCKED,
    CATALYST_SCORE_SUPPORTED,
    CUSTOMER_SUPPLIER,
    DIRECT_ISSUER,
    MACRO,
    PEER,
    RESEARCH_ONLY,
    SECTOR,
    UNRESOLVED,
    normalize_text,
)


CATALYST_EVIDENCE_SCHEMA_VERSION = 1
CATALYST_EVIDENCE_PROFILE = "provider-neutral-catalyst-evidence-v1"

CURRENT = "CURRENT"
STALE = "STALE"
UNKNOWN_TIMESTAMP = "UNKNOWN_TIMESTAMP"
SOURCE_OUTAGE = "SOURCE_OUTAGE"
UNRESOLVED_STATE = "UNRESOLVED"
DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
CATALYST_EVIDENCE_STATES = frozenset(
    {
        CURRENT,
        STALE,
        UNKNOWN_TIMESTAMP,
        SOURCE_OUTAGE,
        UNRESOLVED_STATE,
        DUPLICATE_CONTENT,
    }
)

OUTAGE = "OUTAGE"
RECOVERED = "RECOVERED"
AVAILABLE = "AVAILABLE"
SOURCE_AVAILABILITY_STATES = frozenset({OUTAGE, RECOVERED})

CREATED = "CREATED"
REVISED = "REVISED"
DUPLICATE = "DUPLICATE"

CATALYST_DISCOVERED = "CATALYST_DISCOVERED"
CATALYST_CONTENT_CHANGED = "CATALYST_CONTENT_CHANGED"
CATALYST_ATTRIBUTION_CHANGED = "CATALYST_ATTRIBUTION_CHANGED"
CATALYST_AUTHORITY_CHANGED = "CATALYST_AUTHORITY_CHANGED"
CATALYST_SOURCE_METADATA_CHANGED = "CATALYST_SOURCE_METADATA_CHANGED"
CATALYST_DUPLICATE_STATUS_CHANGED = "CATALYST_DUPLICATE_STATUS_CHANGED"
CATALYST_BECAME_STALE = "CATALYST_BECAME_STALE"
CATALYST_BECAME_CURRENT = "CATALYST_BECAME_CURRENT"
CATALYST_BECAME_UNRESOLVED = "CATALYST_BECAME_UNRESOLVED"
SOURCE_RECOVERED = "SOURCE_RECOVERED"

REVISION_MATERIAL_DELTA_KINDS = frozenset(
    {
        CATALYST_DISCOVERED,
        CATALYST_CONTENT_CHANGED,
        CATALYST_ATTRIBUTION_CHANGED,
        CATALYST_AUTHORITY_CHANGED,
        CATALYST_SOURCE_METADATA_CHANGED,
        CATALYST_DUPLICATE_STATUS_CHANGED,
    }
)
STATE_MATERIAL_DELTA_KINDS = frozenset(
    {
        CATALYST_BECAME_STALE,
        CATALYST_BECAME_CURRENT,
        CATALYST_BECAME_UNRESOLVED,
        CATALYST_AUTHORITY_CHANGED,
        SOURCE_OUTAGE,
        SOURCE_RECOVERED,
    }
)

RELATIONSHIP_TYPES = frozenset(
    {DIRECT_ISSUER, SECTOR, PEER, CUSTOMER_SUPPLIER, MACRO, UNRESOLVED}
)
SCORE_AUTHORITIES = frozenset(
    {CATALYST_SCORE_SUPPORTED, CATALYST_SCORE_BLOCKED}
)

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class CatalystEvidenceError(ValueError):
    """Raised when catalyst evidence is ambiguous, conflicting, or tampered."""


@dataclass(frozen=True)
class CatalystEvidencePolicy:
    policy_version: str
    maximum_age_seconds: int
    future_tolerance_seconds: int
    material_delta_profile: str

    @property
    def fingerprint(self) -> str:
        return fingerprint_payload(asdict(self))


@dataclass(frozen=True)
class CatalystObservation:
    source_identity: str
    source_article_id: str
    provider: str
    source_name: str
    candidate_symbol: str
    candidate_company: str
    headline: str
    summary: str
    published_at: str
    provider_timestamp: str
    receipt_timestamp: str
    relationship_type: str
    relationship_evidence: str
    score_authority: str
    canonical_url: str = ""
    mentioned_symbol: str = ""
    mentioned_company: str = ""
    notes: str = ""


@dataclass(frozen=True)
class CatalystRevision:
    sequence: int
    event_id: str
    revision_number: int
    revision_id: str
    previous_revision_id: str
    source_article_fingerprint: str
    source_identity: str
    source_article_id: str
    provider: str
    source_name: str
    candidate_symbol: str
    candidate_company: str
    headline: str
    summary: str
    published_at: str
    provider_timestamp: str
    receipt_timestamp: str
    relationship_type: str
    relationship_evidence: str
    score_authority: str
    canonical_url: str
    mentioned_symbol: str
    mentioned_company: str
    notes: str
    visibility: str
    observation_fingerprint: str
    semantic_fingerprint: str
    content_event_fingerprint: str
    duplicate_of_event_id: str
    is_duplicate: bool
    evidence_fingerprint: str
    material_delta_kinds: tuple[str, ...]
    triggers_reevaluation: bool
    policy_version: str
    policy_fingerprint: str
    maximum_age_seconds: int
    future_tolerance_seconds: int
    material_delta_profile: str
    fingerprint: str
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


@dataclass(frozen=True)
class CatalystMaterialDeltaEvent:
    sequence: int
    delta_id: str
    event_id: str
    revision_id: str
    previous_revision_id: str
    candidate_symbol: str
    source_identity: str
    occurred_at: str
    delta_kinds: tuple[str, ...]
    evidence_fingerprint: str
    triggers_reevaluation: bool
    fingerprint: str
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


@dataclass(frozen=True)
class CatalystAvailabilityEvent:
    sequence: int
    event_id: str
    source_identity: str
    status: str
    occurred_at: str
    reason: str
    previous_event_id: str
    material_delta_kind: str
    triggers_reevaluation: bool
    fingerprint: str
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


@dataclass(frozen=True)
class CatalystEvidenceLedger:
    revisions: tuple[CatalystRevision, ...] = field(default_factory=tuple)
    material_deltas: tuple[CatalystMaterialDeltaEvent, ...] = field(
        default_factory=tuple
    )
    availability_events: tuple[CatalystAvailabilityEvent, ...] = field(
        default_factory=tuple
    )
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


@dataclass(frozen=True)
class CatalystObservationResult:
    status: str
    revision: CatalystRevision
    material_delta: CatalystMaterialDeltaEvent | None


@dataclass(frozen=True)
class CatalystAvailabilityResult:
    status: str
    event: CatalystAvailabilityEvent


@dataclass(frozen=True)
class CatalystEvidenceSnapshot:
    snapshot_id: str
    event_id: str
    revision_id: str
    evaluated_at: str
    candidate_symbol: str
    candidate_company: str
    source_identity: str
    source_article_id: str
    provider: str
    source_name: str
    canonical_url: str
    headline: str
    summary: str
    published_at: str
    provider_timestamp: str
    receipt_timestamp: str
    relationship_type: str
    relationship_evidence: str
    mentioned_symbol: str
    mentioned_company: str
    content_event_fingerprint: str
    duplicate_of_event_id: str
    is_duplicate: bool
    evidence_state: str
    age_seconds: float | None
    availability_status: str
    availability_event_id: str
    stored_score_authority: str
    effective_score_authority: str
    visibility: str
    can_initiate_trade: bool
    policy_version: str
    policy_fingerprint: str
    revision_fingerprint: str
    fingerprint: str
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


@dataclass(frozen=True)
class CatalystStateDeltaEvent:
    delta_id: str
    event_id: str
    previous_snapshot_id: str
    current_snapshot_id: str
    occurred_at: str
    delta_kinds: tuple[str, ...]
    triggers_reevaluation: bool
    fingerprint: str
    schema_version: int = CATALYST_EVIDENCE_SCHEMA_VERSION
    profile: str = CATALYST_EVIDENCE_PROFILE


class CatalystEvidenceStore:
    """Atomic append-only JSON store for catalyst revisions and availability."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> CatalystEvidenceLedger:
        with self._lock:
            if not self.path.exists():
                return CatalystEvidenceLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CatalystEvidenceError(
                    f"Catalyst evidence cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def append_revision(
        self,
        revision: CatalystRevision,
        material_delta: CatalystMaterialDeltaEvent | None,
    ) -> CatalystRevision:
        with self._lock:
            ledger = self.load()
            existing = next(
                (
                    item
                    for item in ledger.revisions
                    if item.revision_id == revision.revision_id
                ),
                None,
            )
            if existing is not None:
                if existing != revision:
                    raise CatalystEvidenceError(
                        "Catalyst revision identity was reused with conflicting evidence."
                    )
                return existing
            if revision.sequence != len(ledger.revisions) + 1:
                raise CatalystEvidenceError(
                    "Catalyst revision sequence was not append-only."
                )
            if material_delta is not None and material_delta.sequence != len(
                ledger.material_deltas
            ) + 1:
                raise CatalystEvidenceError(
                    "Catalyst material-delta sequence was not append-only."
                )
            updated = replace(
                ledger,
                revisions=(*ledger.revisions, revision),
                material_deltas=(
                    (*ledger.material_deltas, material_delta)
                    if material_delta is not None
                    else ledger.material_deltas
                ),
            )
            validate_ledger(updated)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(updated)))
            return revision

    def append_availability(
        self, event: CatalystAvailabilityEvent
    ) -> CatalystAvailabilityEvent:
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
                if existing != event:
                    raise CatalystEvidenceError(
                        "Catalyst availability identity was reused with conflicting evidence."
                    )
                return existing
            if event.sequence != len(ledger.availability_events) + 1:
                raise CatalystEvidenceError(
                    "Catalyst availability sequence was not append-only."
                )
            updated = replace(
                ledger,
                availability_events=(*ledger.availability_events, event),
            )
            validate_ledger(updated)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(updated)))
            return event


class CatalystEvidenceCoordinator:
    """Records supplied evidence without provider or decision authority."""

    def __init__(
        self,
        store: CatalystEvidenceStore,
        *,
        policy: CatalystEvidencePolicy,
    ) -> None:
        validate_policy(policy)
        self.store = store
        self.policy = policy

    def observe(self, observation: CatalystObservation) -> CatalystObservationResult:
        normalized = normalize_observation(observation, self.policy)
        ledger = self.store.load()
        if _source_is_out(
            ledger,
            normalized.source_identity,
            _timestamp(normalized.receipt_timestamp, "Receipt timestamp"),
        ):
            raise CatalystEvidenceError(
                "Catalyst source outage must be explicitly recovered before observation."
            )
        event_id = expected_catalyst_event_id(
            normalized.source_identity,
            normalized.source_article_id,
            normalized.candidate_symbol,
        )
        previous = next(
            (
                item
                for item in reversed(ledger.revisions)
                if item.event_id == event_id
            ),
            None,
        )
        observation_fingerprint = fingerprint_payload(asdict(normalized))
        if previous is not None and previous.observation_fingerprint == observation_fingerprint:
            return CatalystObservationResult(DUPLICATE, previous, None)
        if previous is not None:
            _validate_source_chain(previous, normalized)
            if _timestamp(normalized.receipt_timestamp, "Receipt timestamp") <= _timestamp(
                previous.receipt_timestamp, "Previous receipt timestamp"
            ):
                raise CatalystEvidenceError(
                    "Catalyst revision receipt chronology was not strictly increasing."
                )

        semantic_fingerprint = fingerprint_payload(
            semantic_observation_payload(normalized)
        )
        content_event_fingerprint = fingerprint_payload(
            content_event_payload(normalized)
        )
        duplicate = next(
            (
                item
                for item in ledger.revisions
                if item.event_id != event_id
                and item.content_event_fingerprint == content_event_fingerprint
            ),
            None,
        )
        duplicate_of_event_id = duplicate.event_id if duplicate else ""
        if duplicate is not None:
            delta_kinds = (
                (CATALYST_DUPLICATE_STATUS_CHANGED,)
                if previous is not None and not previous.is_duplicate
                else ()
            )
        else:
            delta_kinds = revision_delta_kinds(previous, normalized)
            if previous is not None and previous.is_duplicate:
                delta_kinds = (
                    CATALYST_DUPLICATE_STATUS_CHANGED,
                    *delta_kinds,
                )
        revision_number = previous.revision_number + 1 if previous else 1
        previous_revision_id = previous.revision_id if previous else ""
        source_article_fingerprint = expected_source_article_fingerprint(
            normalized.source_identity, normalized.source_article_id
        )
        evidence_payload = revision_evidence_payload(
            normalized,
            event_id=event_id,
            revision_number=revision_number,
            previous_revision_id=previous_revision_id,
            source_article_fingerprint=source_article_fingerprint,
            observation_fingerprint=observation_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            content_event_fingerprint=content_event_fingerprint,
            duplicate_of_event_id=duplicate_of_event_id,
            is_duplicate=duplicate is not None,
            delta_kinds=delta_kinds,
            policy=self.policy,
        )
        evidence_fingerprint = fingerprint_payload(evidence_payload)
        revision_id = expected_revision_id(
            event_id, revision_number, evidence_fingerprint
        )
        revision = CatalystRevision(
            sequence=len(ledger.revisions) + 1,
            revision_id=revision_id,
            evidence_fingerprint=evidence_fingerprint,
            visibility=RESEARCH_ONLY,
            triggers_reevaluation=bool(delta_kinds),
            fingerprint="",
            **evidence_payload,
        )
        revision = replace(
            revision, fingerprint=fingerprint_payload(revision_fingerprint_payload(revision))
        )
        material_delta = None
        if delta_kinds:
            material_delta = build_revision_material_delta(
                revision,
                sequence=len(ledger.material_deltas) + 1,
            )
        self.store.append_revision(revision, material_delta)
        return CatalystObservationResult(
            CREATED if previous is None else REVISED,
            revision,
            material_delta,
        )

    def record_availability(
        self,
        *,
        source_identity: str,
        status: str,
        occurred_at: datetime,
        reason: str,
    ) -> CatalystAvailabilityResult:
        source = _identity(source_identity, "Catalyst source identity")
        normalized_status = str(status).strip().upper()
        if normalized_status not in SOURCE_AVAILABILITY_STATES:
            raise CatalystEvidenceError(
                "Catalyst source availability status is unsupported."
            )
        occurred = _iso(_aware(occurred_at, "Availability timestamp"))
        normalized_reason = _required_text(reason, "Availability reason")
        ledger = self.store.load()
        event_id = expected_availability_event_id(
            source_identity=source,
            status=normalized_status,
            occurred_at=occurred,
            reason=normalized_reason,
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
            return CatalystAvailabilityResult(DUPLICATE, existing)
        previous = next(
            (
                item
                for item in reversed(ledger.availability_events)
                if item.source_identity == source
            ),
            None,
        )
        if previous and _timestamp(occurred, "Availability timestamp") <= _timestamp(
            previous.occurred_at, "Previous availability timestamp"
        ):
            raise CatalystEvidenceError(
                "Catalyst availability chronology was not strictly increasing."
            )
        if normalized_status == RECOVERED and (
            previous is None or previous.status != OUTAGE
        ):
            raise CatalystEvidenceError(
                "Catalyst source recovery requires a prior outage."
            )
        material_delta_kind = ""
        if normalized_status == OUTAGE and (
            previous is None or previous.status != OUTAGE
        ):
            material_delta_kind = SOURCE_OUTAGE
        elif normalized_status == RECOVERED:
            material_delta_kind = SOURCE_RECOVERED
        event = CatalystAvailabilityEvent(
            sequence=len(ledger.availability_events) + 1,
            event_id=event_id,
            source_identity=source,
            status=normalized_status,
            occurred_at=occurred,
            reason=normalized_reason,
            previous_event_id=previous.event_id if previous else "",
            material_delta_kind=material_delta_kind,
            triggers_reevaluation=bool(material_delta_kind),
            fingerprint="",
        )
        event = replace(
            event,
            fingerprint=fingerprint_payload(availability_fingerprint_payload(event)),
        )
        self.store.append_availability(event)
        return CatalystAvailabilityResult(CREATED, event)

    def snapshot(
        self,
        event_id: str,
        *,
        evaluated_at: datetime,
    ) -> CatalystEvidenceSnapshot:
        return evaluate_catalyst_evidence(
            self.store.load(),
            event_id=event_id,
            policy=self.policy,
            evaluated_at=evaluated_at,
        )

    def snapshots(
        self,
        *,
        evaluated_at: datetime,
    ) -> tuple[CatalystEvidenceSnapshot, ...]:
        ledger = self.store.load()
        event_ids = tuple(dict.fromkeys(item.event_id for item in ledger.revisions))
        snapshots = [
            evaluate_catalyst_evidence(
                ledger,
                event_id=event_id,
                policy=self.policy,
                evaluated_at=evaluated_at,
            )
            for event_id in event_ids
            if any(
                item.event_id == event_id
                and _timestamp(item.receipt_timestamp, "Receipt timestamp")
                <= _aware(evaluated_at, "Evaluation timestamp")
                for item in ledger.revisions
            )
        ]
        return tuple(sorted(snapshots, key=lambda item: (item.candidate_symbol, item.event_id)))


def evaluate_catalyst_evidence(
    ledger: CatalystEvidenceLedger,
    *,
    event_id: str,
    policy: CatalystEvidencePolicy,
    evaluated_at: datetime,
) -> CatalystEvidenceSnapshot:
    validate_ledger(ledger)
    validate_policy(policy)
    event_identity = _sha256(event_id, "Catalyst event identity")
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    eligible = [
        item
        for item in ledger.revisions
        if item.event_id == event_identity
        and _timestamp(item.receipt_timestamp, "Receipt timestamp") <= evaluated
    ]
    if not eligible:
        raise CatalystEvidenceError(
            "Catalyst evidence was unavailable at the requested evaluation time."
        )
    revision = eligible[-1]
    availability = _latest_availability(
        ledger, revision.source_identity, evaluated
    )
    published = (
        _timestamp(revision.published_at, "Publication timestamp")
        if revision.published_at
        else None
    )
    age_seconds = (
        round(max(0.0, (evaluated - published).total_seconds()), 3)
        if published is not None
        else None
    )
    if availability is not None and availability.status == OUTAGE:
        state = SOURCE_OUTAGE
    elif published is None:
        state = UNKNOWN_TIMESTAMP
    elif age_seconds is not None and age_seconds > policy.maximum_age_seconds:
        state = STALE
    elif revision.is_duplicate:
        state = DUPLICATE_CONTENT
    elif (
        revision.relationship_type == UNRESOLVED
        or revision.score_authority != CATALYST_SCORE_SUPPORTED
    ):
        state = UNRESOLVED_STATE
    else:
        state = CURRENT
    effective_authority = (
        CATALYST_SCORE_SUPPORTED
        if state == CURRENT
        and revision.score_authority == CATALYST_SCORE_SUPPORTED
        else CATALYST_SCORE_BLOCKED
    )
    payload = {
        "event_id": revision.event_id,
        "revision_id": revision.revision_id,
        "evaluated_at": _iso(evaluated),
        "candidate_symbol": revision.candidate_symbol,
        "candidate_company": revision.candidate_company,
        "source_identity": revision.source_identity,
        "source_article_id": revision.source_article_id,
        "provider": revision.provider,
        "source_name": revision.source_name,
        "canonical_url": revision.canonical_url,
        "headline": revision.headline,
        "summary": revision.summary,
        "published_at": revision.published_at,
        "provider_timestamp": revision.provider_timestamp,
        "receipt_timestamp": revision.receipt_timestamp,
        "relationship_type": revision.relationship_type,
        "relationship_evidence": revision.relationship_evidence,
        "mentioned_symbol": revision.mentioned_symbol,
        "mentioned_company": revision.mentioned_company,
        "content_event_fingerprint": revision.content_event_fingerprint,
        "duplicate_of_event_id": revision.duplicate_of_event_id,
        "is_duplicate": revision.is_duplicate,
        "evidence_state": state,
        "age_seconds": age_seconds,
        "availability_status": (
            availability.status if availability is not None else AVAILABLE
        ),
        "availability_event_id": (
            availability.event_id if availability is not None else ""
        ),
        "stored_score_authority": revision.score_authority,
        "effective_score_authority": effective_authority,
        "visibility": RESEARCH_ONLY,
        "can_initiate_trade": False,
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "revision_fingerprint": revision.fingerprint,
        "schema_version": CATALYST_EVIDENCE_SCHEMA_VERSION,
        "profile": CATALYST_EVIDENCE_PROFILE,
    }
    fingerprint = fingerprint_payload(payload)
    return CatalystEvidenceSnapshot(
        snapshot_id=f"catalyst-snapshot-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def compare_catalyst_snapshots(
    previous: CatalystEvidenceSnapshot,
    current: CatalystEvidenceSnapshot,
) -> CatalystStateDeltaEvent | None:
    validate_snapshot(previous)
    validate_snapshot(current)
    if previous.event_id != current.event_id:
        raise CatalystEvidenceError(
            "Catalyst state comparison requires one event identity."
        )
    if _timestamp(current.evaluated_at, "Current evaluation timestamp") < _timestamp(
        previous.evaluated_at, "Previous evaluation timestamp"
    ):
        raise CatalystEvidenceError(
            "Catalyst state comparison cannot move backward in time."
        )
    kinds: list[str] = []
    if previous.evidence_state != current.evidence_state:
        if current.evidence_state == SOURCE_OUTAGE:
            kinds.append(SOURCE_OUTAGE)
        elif previous.evidence_state == SOURCE_OUTAGE:
            kinds.append(SOURCE_RECOVERED)
        if current.evidence_state == STALE:
            kinds.append(CATALYST_BECAME_STALE)
        elif current.evidence_state == CURRENT:
            kinds.append(CATALYST_BECAME_CURRENT)
        elif current.evidence_state == UNRESOLVED_STATE:
            kinds.append(CATALYST_BECAME_UNRESOLVED)
    if previous.effective_score_authority != current.effective_score_authority:
        kinds.append(CATALYST_AUTHORITY_CHANGED)
    normalized_kinds = tuple(dict.fromkeys(kinds))
    if not normalized_kinds:
        return None
    payload = {
        "event_id": current.event_id,
        "previous_snapshot_id": previous.snapshot_id,
        "current_snapshot_id": current.snapshot_id,
        "occurred_at": current.evaluated_at,
        "delta_kinds": normalized_kinds,
        "triggers_reevaluation": True,
        "schema_version": CATALYST_EVIDENCE_SCHEMA_VERSION,
        "profile": CATALYST_EVIDENCE_PROFILE,
    }
    fingerprint = fingerprint_payload(payload)
    return CatalystStateDeltaEvent(
        delta_id=f"catalyst-state-delta-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def normalize_observation(
    observation: CatalystObservation,
    policy: CatalystEvidencePolicy,
) -> CatalystObservation:
    validate_policy(policy)
    relationship = str(observation.relationship_type).strip().upper()
    authority = str(observation.score_authority).strip().upper()
    if relationship not in RELATIONSHIP_TYPES:
        raise CatalystEvidenceError("Catalyst relationship type is unsupported.")
    if authority not in SCORE_AUTHORITIES:
        raise CatalystEvidenceError("Catalyst score authority is unsupported.")
    if relationship == UNRESOLVED and authority != CATALYST_SCORE_BLOCKED:
        raise CatalystEvidenceError(
            "Unresolved catalyst attribution must remain score-authority blocked."
        )
    source_identity = _identity(
        observation.source_identity, "Catalyst source identity"
    )
    source_article_id = _identity(
        observation.source_article_id, "Catalyst source article identity"
    )
    provider_timestamp = _iso(
        _timestamp(observation.provider_timestamp, "Provider timestamp")
    )
    receipt_timestamp = _iso(
        _timestamp(observation.receipt_timestamp, "Receipt timestamp")
    )
    provider_time = _timestamp(provider_timestamp, "Provider timestamp")
    receipt_time = _timestamp(receipt_timestamp, "Receipt timestamp")
    tolerance = timedelta(seconds=policy.future_tolerance_seconds)
    if provider_time > receipt_time + tolerance:
        raise CatalystEvidenceError(
            "Catalyst provider timestamp exceeds receipt-time tolerance."
        )
    published_at = ""
    if str(observation.published_at).strip():
        published_time = _timestamp(
            observation.published_at, "Publication timestamp"
        )
        if published_time > receipt_time + tolerance:
            raise CatalystEvidenceError(
                "Catalyst publication timestamp exceeds receipt-time tolerance."
            )
        published_at = _iso(published_time)
    mentioned_symbol = str(observation.mentioned_symbol).strip().upper()
    if mentioned_symbol:
        _symbol(mentioned_symbol, "Mentioned symbol")
    return CatalystObservation(
        source_identity=source_identity,
        source_article_id=source_article_id,
        provider=_required_text(observation.provider, "Catalyst provider"),
        source_name=_required_text(observation.source_name, "Catalyst source name"),
        candidate_symbol=_symbol(
            observation.candidate_symbol, "Catalyst candidate symbol"
        ),
        candidate_company=_optional_text(observation.candidate_company),
        headline=_required_text(observation.headline, "Catalyst headline"),
        summary=_optional_text(observation.summary),
        published_at=published_at,
        provider_timestamp=provider_timestamp,
        receipt_timestamp=receipt_timestamp,
        relationship_type=relationship,
        relationship_evidence=_required_text(
            observation.relationship_evidence,
            "Catalyst relationship evidence",
        ),
        score_authority=authority,
        canonical_url=_optional_text(observation.canonical_url),
        mentioned_symbol=mentioned_symbol,
        mentioned_company=_optional_text(observation.mentioned_company),
        notes=_optional_text(observation.notes),
    )


def revision_delta_kinds(
    previous: CatalystRevision | None,
    observation: CatalystObservation,
) -> tuple[str, ...]:
    if previous is None:
        return (CATALYST_DISCOVERED,)
    kinds: list[str] = []
    if (
        normalize_text(previous.headline) != normalize_text(observation.headline)
        or normalize_text(previous.summary) != normalize_text(observation.summary)
    ):
        kinds.append(CATALYST_CONTENT_CHANGED)
    if any(
        (
            previous.relationship_type != observation.relationship_type,
            previous.relationship_evidence != observation.relationship_evidence,
            previous.mentioned_symbol != observation.mentioned_symbol,
            previous.mentioned_company != observation.mentioned_company,
            previous.candidate_company != observation.candidate_company,
        )
    ):
        kinds.append(CATALYST_ATTRIBUTION_CHANGED)
    if previous.score_authority != observation.score_authority:
        kinds.append(CATALYST_AUTHORITY_CHANGED)
    if (
        previous.canonical_url != observation.canonical_url
        or previous.published_at != observation.published_at
    ):
        kinds.append(CATALYST_SOURCE_METADATA_CHANGED)
    return tuple(kinds)


def semantic_observation_payload(
    observation: CatalystObservation,
) -> dict[str, object]:
    return {
        "headline": normalize_text(observation.headline),
        "summary": normalize_text(observation.summary),
        "published_at": observation.published_at,
        "canonical_url": observation.canonical_url,
        "candidate_company": observation.candidate_company,
        "relationship_type": observation.relationship_type,
        "relationship_evidence": observation.relationship_evidence,
        "mentioned_symbol": observation.mentioned_symbol,
        "mentioned_company": observation.mentioned_company,
        "score_authority": observation.score_authority,
    }


def content_event_payload(
    observation: CatalystObservation,
) -> dict[str, object]:
    return {
        "source_identity": observation.source_identity,
        "candidate_symbol": observation.candidate_symbol,
        "headline": normalize_text(observation.headline),
        "summary": normalize_text(observation.summary),
        "relationship_type": observation.relationship_type,
        "relationship_evidence": normalize_text(
            observation.relationship_evidence
        ),
        "mentioned_symbol": observation.mentioned_symbol,
        "mentioned_company": normalize_text(observation.mentioned_company),
        "score_authority": observation.score_authority,
    }


def revision_evidence_payload(
    observation: CatalystObservation,
    *,
    event_id: str,
    revision_number: int,
    previous_revision_id: str,
    source_article_fingerprint: str,
    observation_fingerprint: str,
    semantic_fingerprint: str,
    content_event_fingerprint: str,
    duplicate_of_event_id: str,
    is_duplicate: bool,
    delta_kinds: tuple[str, ...],
    policy: CatalystEvidencePolicy,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "revision_number": revision_number,
        "previous_revision_id": previous_revision_id,
        "source_article_fingerprint": source_article_fingerprint,
        **asdict(observation),
        "observation_fingerprint": observation_fingerprint,
        "semantic_fingerprint": semantic_fingerprint,
        "content_event_fingerprint": content_event_fingerprint,
        "duplicate_of_event_id": duplicate_of_event_id,
        "is_duplicate": is_duplicate,
        "material_delta_kinds": delta_kinds,
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "maximum_age_seconds": policy.maximum_age_seconds,
        "future_tolerance_seconds": policy.future_tolerance_seconds,
        "material_delta_profile": policy.material_delta_profile,
    }


def build_revision_material_delta(
    revision: CatalystRevision,
    *,
    sequence: int,
) -> CatalystMaterialDeltaEvent:
    payload = {
        "sequence": sequence,
        "event_id": revision.event_id,
        "revision_id": revision.revision_id,
        "previous_revision_id": revision.previous_revision_id,
        "candidate_symbol": revision.candidate_symbol,
        "source_identity": revision.source_identity,
        "occurred_at": revision.receipt_timestamp,
        "delta_kinds": revision.material_delta_kinds,
        "evidence_fingerprint": revision.evidence_fingerprint,
        "triggers_reevaluation": True,
        "schema_version": CATALYST_EVIDENCE_SCHEMA_VERSION,
        "profile": CATALYST_EVIDENCE_PROFILE,
    }
    fingerprint = fingerprint_payload(payload)
    return CatalystMaterialDeltaEvent(
        delta_id=f"catalyst-delta-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def expected_catalyst_event_id(
    source_identity: str,
    source_article_id: str,
    candidate_symbol: str,
) -> str:
    return fingerprint_payload(
        {
            "profile": CATALYST_EVIDENCE_PROFILE,
            "source_identity": _identity(
                source_identity, "Catalyst source identity"
            ),
            "source_article_id": _identity(
                source_article_id, "Catalyst source article identity"
            ),
            "candidate_symbol": _symbol(
                candidate_symbol, "Catalyst candidate symbol"
            ),
        }
    )


def expected_source_article_fingerprint(
    source_identity: str,
    source_article_id: str,
) -> str:
    return fingerprint_payload(
        {
            "source_identity": source_identity,
            "source_article_id": source_article_id,
        }
    )


def expected_revision_id(
    event_id: str,
    revision_number: int,
    evidence_fingerprint: str,
) -> str:
    return fingerprint_payload(
        {
            "event_id": _sha256(event_id, "Catalyst event identity"),
            "revision_number": revision_number,
            "evidence_fingerprint": _sha256(
                evidence_fingerprint, "Catalyst evidence fingerprint"
            ),
        }
    )


def expected_availability_event_id(
    *,
    source_identity: str,
    status: str,
    occurred_at: str,
    reason: str,
) -> str:
    return fingerprint_payload(
        {
            "profile": CATALYST_EVIDENCE_PROFILE,
            "source_identity": _identity(
                source_identity, "Catalyst source identity"
            ),
            "status": str(status).strip().upper(),
            "occurred_at": _iso(
                _timestamp(occurred_at, "Availability timestamp")
            ),
            "reason": _required_text(reason, "Availability reason"),
        }
    )


def validate_policy(policy: CatalystEvidencePolicy) -> None:
    _required_text(policy.policy_version, "Catalyst policy version")
    _required_text(policy.material_delta_profile, "Material-delta profile")
    if (
        not isinstance(policy.maximum_age_seconds, int)
        or isinstance(policy.maximum_age_seconds, bool)
        or policy.maximum_age_seconds <= 0
    ):
        raise CatalystEvidenceError(
            "Catalyst maximum age must be a positive integer."
        )
    if (
        not isinstance(policy.future_tolerance_seconds, int)
        or isinstance(policy.future_tolerance_seconds, bool)
        or policy.future_tolerance_seconds < 0
    ):
        raise CatalystEvidenceError(
            "Catalyst future tolerance must be a nonnegative integer."
        )


def validate_ledger(ledger: CatalystEvidenceLedger) -> None:
    if type(ledger.schema_version) is not int:
        raise CatalystEvidenceError("Catalyst ledger schema version is invalid.")
    if ledger.schema_version != CATALYST_EVIDENCE_SCHEMA_VERSION:
        raise CatalystEvidenceError("Catalyst ledger schema version is unsupported.")
    if ledger.profile != CATALYST_EVIDENCE_PROFILE:
        raise CatalystEvidenceError("Catalyst ledger profile is unsupported.")
    revisions_by_event: dict[str, list[CatalystRevision]] = {}
    for expected_sequence, revision in enumerate(ledger.revisions, start=1):
        if revision.sequence != expected_sequence:
            raise CatalystEvidenceError("Catalyst revision sequence is invalid.")
        validate_revision(revision)
        revisions_by_event.setdefault(revision.event_id, []).append(revision)
    for revisions in revisions_by_event.values():
        for index, revision in enumerate(revisions):
            expected_number = index + 1
            expected_previous = revisions[index - 1].revision_id if index else ""
            if revision.revision_number != expected_number:
                raise CatalystEvidenceError("Catalyst revision number skipped its chain.")
            if revision.previous_revision_id != expected_previous:
                raise CatalystEvidenceError(
                    "Catalyst revision predecessor chain is invalid."
                )
            if index and _timestamp(
                revision.receipt_timestamp, "Revision receipt timestamp"
            ) <= _timestamp(
                revisions[index - 1].receipt_timestamp,
                "Previous revision receipt timestamp",
            ):
                raise CatalystEvidenceError(
                    "Catalyst revision receipt chronology is invalid."
                )
            if index == 0 and not revision.is_duplicate and revision.material_delta_kinds != (
                CATALYST_DISCOVERED,
            ):
                raise CatalystEvidenceError(
                    "Catalyst revision chain must begin with discovery."
                )
            if revision.is_duplicate and any(
                kind != CATALYST_DUPLICATE_STATUS_CHANGED
                for kind in revision.material_delta_kinds
            ):
                raise CatalystEvidenceError(
                    "Duplicate catalyst content can only change duplicate status."
                )
            if index > 0 and CATALYST_DISCOVERED in revision.material_delta_kinds:
                raise CatalystEvidenceError(
                    "Catalyst discovery cannot recur inside one revision chain."
                )
    content_seen_by_event: dict[str, set[str]] = {}
    for revision in ledger.revisions:
        if revision.is_duplicate:
            source_fingerprints = content_seen_by_event.get(
                revision.duplicate_of_event_id
            )
            if not source_fingerprints:
                raise CatalystEvidenceError(
                    "Duplicate catalyst evidence lacks an earlier source event."
                )
            if revision.content_event_fingerprint not in source_fingerprints:
                raise CatalystEvidenceError(
                    "Duplicate catalyst content fingerprint is contradictory."
                )
        content_seen_by_event.setdefault(revision.event_id, set()).add(
            revision.content_event_fingerprint
        )
    delta_by_revision: dict[str, CatalystMaterialDeltaEvent] = {}
    for expected_sequence, delta in enumerate(ledger.material_deltas, start=1):
        if delta.sequence != expected_sequence:
            raise CatalystEvidenceError(
                "Catalyst material-delta sequence is invalid."
            )
        validate_material_delta(delta)
        if delta.revision_id in delta_by_revision:
            raise CatalystEvidenceError(
                "Catalyst revision has duplicate material-delta evidence."
            )
        delta_by_revision[delta.revision_id] = delta
    revision_ids = {item.revision_id for item in ledger.revisions}
    if any(revision_id not in revision_ids for revision_id in delta_by_revision):
        raise CatalystEvidenceError(
            "Catalyst material delta references an unknown revision."
        )
    for revision in ledger.revisions:
        delta = delta_by_revision.get(revision.revision_id)
        if bool(revision.material_delta_kinds) != (delta is not None):
            raise CatalystEvidenceError(
                "Catalyst material revision and delta evidence disagree."
            )
        if delta is not None and (
            delta.event_id != revision.event_id
            or delta.evidence_fingerprint != revision.evidence_fingerprint
            or delta.delta_kinds != revision.material_delta_kinds
        ):
            raise CatalystEvidenceError(
                "Catalyst material delta does not match its revision."
            )
    availability_by_source: dict[str, list[CatalystAvailabilityEvent]] = {}
    for expected_sequence, event in enumerate(ledger.availability_events, start=1):
        if event.sequence != expected_sequence:
            raise CatalystEvidenceError(
                "Catalyst availability sequence is invalid."
            )
        validate_availability(event)
        availability_by_source.setdefault(event.source_identity, []).append(event)
    for events in availability_by_source.values():
        for index, event in enumerate(events):
            expected_previous = events[index - 1].event_id if index else ""
            if event.previous_event_id != expected_previous:
                raise CatalystEvidenceError(
                    "Catalyst availability predecessor chain is invalid."
                )
            if index and _timestamp(
                event.occurred_at, "Availability timestamp"
            ) <= _timestamp(
                events[index - 1].occurred_at,
                "Previous availability timestamp",
            ):
                raise CatalystEvidenceError(
                    "Catalyst availability chronology is invalid."
                )
            if event.status == RECOVERED and (
                index == 0 or events[index - 1].status != OUTAGE
            ):
                raise CatalystEvidenceError(
                    "Catalyst recovery does not follow an outage."
                )


def validate_revision(revision: CatalystRevision) -> None:
    if type(revision.sequence) is not int or revision.sequence <= 0:
        raise CatalystEvidenceError("Catalyst revision sequence is invalid.")
    if type(revision.revision_number) is not int or revision.revision_number <= 0:
        raise CatalystEvidenceError("Catalyst revision number is invalid.")
    if type(revision.schema_version) is not int:
        raise CatalystEvidenceError("Catalyst revision schema is invalid.")
    if revision.schema_version != CATALYST_EVIDENCE_SCHEMA_VERSION:
        raise CatalystEvidenceError("Catalyst revision schema is unsupported.")
    if revision.profile != CATALYST_EVIDENCE_PROFILE:
        raise CatalystEvidenceError("Catalyst revision profile is unsupported.")
    if revision.visibility != RESEARCH_ONLY or not isinstance(
        revision.triggers_reevaluation, bool
    ):
        raise CatalystEvidenceError("Catalyst revision authority shape is invalid.")
    if revision.triggers_reevaluation != bool(revision.material_delta_kinds):
        raise CatalystEvidenceError(
            "Catalyst revision trigger does not match material deltas."
        )
    if type(revision.is_duplicate) is not bool or revision.is_duplicate != bool(
        revision.duplicate_of_event_id
    ):
        raise CatalystEvidenceError(
            "Catalyst duplicate identity shape is invalid."
        )
    if revision.duplicate_of_event_id:
        _sha256(revision.duplicate_of_event_id, "Duplicate catalyst event identity")
    if any(kind not in REVISION_MATERIAL_DELTA_KINDS for kind in revision.material_delta_kinds):
        raise CatalystEvidenceError("Catalyst revision material delta is unsupported.")
    policy = CatalystEvidencePolicy(
        policy_version=revision.policy_version,
        maximum_age_seconds=revision.maximum_age_seconds,
        future_tolerance_seconds=revision.future_tolerance_seconds,
        material_delta_profile=revision.material_delta_profile,
    )
    validate_policy(policy)
    if policy.fingerprint != revision.policy_fingerprint:
        raise CatalystEvidenceError("Catalyst revision policy fingerprint is invalid.")
    observation = CatalystObservation(
        source_identity=revision.source_identity,
        source_article_id=revision.source_article_id,
        provider=revision.provider,
        source_name=revision.source_name,
        candidate_symbol=revision.candidate_symbol,
        candidate_company=revision.candidate_company,
        headline=revision.headline,
        summary=revision.summary,
        published_at=revision.published_at,
        provider_timestamp=revision.provider_timestamp,
        receipt_timestamp=revision.receipt_timestamp,
        relationship_type=revision.relationship_type,
        relationship_evidence=revision.relationship_evidence,
        score_authority=revision.score_authority,
        canonical_url=revision.canonical_url,
        mentioned_symbol=revision.mentioned_symbol,
        mentioned_company=revision.mentioned_company,
        notes=revision.notes,
    )
    normalized = normalize_observation(observation, policy)
    if fingerprint_payload(asdict(normalized)) != revision.observation_fingerprint:
        raise CatalystEvidenceError("Catalyst observation fingerprint is invalid.")
    if (
        fingerprint_payload(semantic_observation_payload(normalized))
        != revision.semantic_fingerprint
    ):
        raise CatalystEvidenceError("Catalyst semantic fingerprint is invalid.")
    if (
        fingerprint_payload(content_event_payload(normalized))
        != revision.content_event_fingerprint
    ):
        raise CatalystEvidenceError("Catalyst content-event fingerprint is invalid.")
    if expected_source_article_fingerprint(
        revision.source_identity, revision.source_article_id
    ) != revision.source_article_fingerprint:
        raise CatalystEvidenceError("Catalyst source article fingerprint is invalid.")
    if expected_catalyst_event_id(
        revision.source_identity,
        revision.source_article_id,
        revision.candidate_symbol,
    ) != revision.event_id:
        raise CatalystEvidenceError("Catalyst event identity is invalid.")
    expected_evidence = fingerprint_payload(
        revision_evidence_payload(
            normalized,
            event_id=revision.event_id,
            revision_number=revision.revision_number,
            previous_revision_id=revision.previous_revision_id,
            source_article_fingerprint=revision.source_article_fingerprint,
            observation_fingerprint=revision.observation_fingerprint,
            semantic_fingerprint=revision.semantic_fingerprint,
            content_event_fingerprint=revision.content_event_fingerprint,
            duplicate_of_event_id=revision.duplicate_of_event_id,
            is_duplicate=revision.is_duplicate,
            delta_kinds=revision.material_delta_kinds,
            policy=policy,
        )
    )
    if expected_evidence != revision.evidence_fingerprint:
        raise CatalystEvidenceError("Catalyst evidence fingerprint is invalid.")
    if expected_revision_id(
        revision.event_id,
        revision.revision_number,
        revision.evidence_fingerprint,
    ) != revision.revision_id:
        raise CatalystEvidenceError("Catalyst revision identity is invalid.")
    if fingerprint_payload(revision_fingerprint_payload(revision)) != revision.fingerprint:
        raise CatalystEvidenceError("Catalyst revision fingerprint is invalid.")


def validate_material_delta(delta: CatalystMaterialDeltaEvent) -> None:
    if type(delta.sequence) is not int or delta.sequence <= 0:
        raise CatalystEvidenceError("Catalyst material-delta sequence is invalid.")
    if type(delta.schema_version) is not int or (
        delta.schema_version != CATALYST_EVIDENCE_SCHEMA_VERSION
    ):
        raise CatalystEvidenceError("Catalyst material-delta schema is invalid.")
    if delta.profile != CATALYST_EVIDENCE_PROFILE:
        raise CatalystEvidenceError("Catalyst material-delta profile is invalid.")
    if not delta.delta_kinds or any(
        kind not in REVISION_MATERIAL_DELTA_KINDS for kind in delta.delta_kinds
    ):
        raise CatalystEvidenceError("Catalyst material-delta evidence is invalid.")
    if not delta.triggers_reevaluation:
        raise CatalystEvidenceError("Catalyst material delta must trigger reevaluation.")
    _sha256(delta.event_id, "Catalyst material event identity")
    _sha256(delta.revision_id, "Catalyst material revision identity")
    _sha256(delta.evidence_fingerprint, "Catalyst material evidence fingerprint")
    _timestamp(delta.occurred_at, "Catalyst material-delta timestamp")
    expected_fingerprint = fingerprint_payload(
        material_delta_fingerprint_payload(delta)
    )
    if (
        expected_fingerprint != delta.fingerprint
        or delta.delta_id != f"catalyst-delta-{expected_fingerprint[:24]}"
    ):
        raise CatalystEvidenceError("Catalyst material-delta fingerprint is invalid.")


def validate_availability(event: CatalystAvailabilityEvent) -> None:
    if type(event.sequence) is not int or event.sequence <= 0:
        raise CatalystEvidenceError("Catalyst availability sequence is invalid.")
    if type(event.schema_version) is not int or (
        event.schema_version != CATALYST_EVIDENCE_SCHEMA_VERSION
    ):
        raise CatalystEvidenceError("Catalyst availability schema is invalid.")
    if event.profile != CATALYST_EVIDENCE_PROFILE:
        raise CatalystEvidenceError("Catalyst availability profile is invalid.")
    _identity(event.source_identity, "Catalyst availability source identity")
    if event.status not in SOURCE_AVAILABILITY_STATES:
        raise CatalystEvidenceError("Catalyst availability status is invalid.")
    _timestamp(event.occurred_at, "Catalyst availability timestamp")
    _required_text(event.reason, "Catalyst availability reason")
    if event.material_delta_kind and event.material_delta_kind not in {
        SOURCE_OUTAGE,
        SOURCE_RECOVERED,
    }:
        raise CatalystEvidenceError("Catalyst availability delta is invalid.")
    if event.triggers_reevaluation != bool(event.material_delta_kind):
        raise CatalystEvidenceError(
            "Catalyst availability trigger does not match its delta."
        )
    if expected_availability_event_id(
        source_identity=event.source_identity,
        status=event.status,
        occurred_at=event.occurred_at,
        reason=event.reason,
    ) != event.event_id:
        raise CatalystEvidenceError("Catalyst availability identity is invalid.")
    if fingerprint_payload(availability_fingerprint_payload(event)) != event.fingerprint:
        raise CatalystEvidenceError("Catalyst availability fingerprint is invalid.")


def validate_snapshot(snapshot: CatalystEvidenceSnapshot) -> None:
    if type(snapshot.schema_version) is not int or (
        snapshot.schema_version != CATALYST_EVIDENCE_SCHEMA_VERSION
    ):
        raise CatalystEvidenceError("Catalyst snapshot schema is unsupported.")
    if snapshot.profile != CATALYST_EVIDENCE_PROFILE:
        raise CatalystEvidenceError("Catalyst snapshot profile is unsupported.")
    if snapshot.evidence_state not in CATALYST_EVIDENCE_STATES:
        raise CatalystEvidenceError("Catalyst snapshot state is unsupported.")
    if snapshot.visibility != RESEARCH_ONLY or snapshot.can_initiate_trade:
        raise CatalystEvidenceError("Catalyst snapshot crossed its authority boundary.")
    if snapshot.stored_score_authority not in SCORE_AUTHORITIES or (
        snapshot.effective_score_authority not in SCORE_AUTHORITIES
    ):
        raise CatalystEvidenceError("Catalyst snapshot authority is unsupported.")
    if snapshot.availability_status not in {
        AVAILABLE,
        OUTAGE,
        RECOVERED,
    }:
        raise CatalystEvidenceError("Catalyst snapshot availability is unsupported.")
    if type(snapshot.is_duplicate) is not bool or snapshot.is_duplicate != bool(
        snapshot.duplicate_of_event_id
    ):
        raise CatalystEvidenceError("Catalyst snapshot duplicate shape is invalid.")
    if snapshot.duplicate_of_event_id:
        _sha256(snapshot.duplicate_of_event_id, "Duplicate catalyst event identity")
    _sha256(snapshot.content_event_fingerprint, "Catalyst content fingerprint")
    supported = (
        snapshot.evidence_state == CURRENT
        and snapshot.stored_score_authority == CATALYST_SCORE_SUPPORTED
        and not snapshot.is_duplicate
    )
    expected_authority = (
        CATALYST_SCORE_SUPPORTED if supported else CATALYST_SCORE_BLOCKED
    )
    if snapshot.effective_score_authority != expected_authority:
        raise CatalystEvidenceError(
            "Unsafe catalyst state cannot retain effective score authority."
        )
    if snapshot.age_seconds is not None and (
        isinstance(snapshot.age_seconds, bool)
        or not isinstance(snapshot.age_seconds, (int, float))
        or snapshot.age_seconds < 0
    ):
        raise CatalystEvidenceError("Catalyst snapshot age is invalid.")
    _required_text(snapshot.policy_version, "Catalyst snapshot policy version")
    _sha256(snapshot.policy_fingerprint, "Catalyst snapshot policy fingerprint")
    _sha256(snapshot.revision_fingerprint, "Catalyst snapshot revision fingerprint")
    payload = asdict(snapshot)
    fingerprint = payload.pop("fingerprint")
    snapshot_id = payload.pop("snapshot_id")
    expected = fingerprint_payload(payload)
    if fingerprint != expected or snapshot_id != f"catalyst-snapshot-{expected[:24]}":
        raise CatalystEvidenceError("Catalyst snapshot fingerprint is invalid.")


def ledger_to_wire(ledger: CatalystEvidenceLedger) -> dict[str, object]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "revisions": [asdict(item) for item in ledger.revisions],
        "material_deltas": [asdict(item) for item in ledger.material_deltas],
        "availability_events": [asdict(item) for item in ledger.availability_events],
    }


def ledger_from_wire(payload: object) -> CatalystEvidenceLedger:
    if not isinstance(payload, Mapping):
        raise CatalystEvidenceError("Catalyst ledger payload must be an object.")
    try:
        raw_revisions = payload.get("revisions", ())
        raw_deltas = payload.get("material_deltas", ())
        raw_availability = payload.get("availability_events", ())
        for name, values in (
            ("revisions", raw_revisions),
            ("material_deltas", raw_deltas),
            ("availability_events", raw_availability),
        ):
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(item, Mapping) for item in values
            ):
                raise CatalystEvidenceError(
                    f"Catalyst ledger {name} collection is malformed."
                )
        revisions = tuple(
            CatalystRevision(
                **{
                    **item,
                    "material_delta_kinds": tuple(item.get("material_delta_kinds", ())),
                }
            )
            for item in raw_revisions
        )
        material_deltas = tuple(
            CatalystMaterialDeltaEvent(
                **{
                    **item,
                    "delta_kinds": tuple(item.get("delta_kinds", ())),
                }
            )
            for item in raw_deltas
        )
        availability = tuple(
            CatalystAvailabilityEvent(**item)
            for item in raw_availability
        )
        return CatalystEvidenceLedger(
            revisions=revisions,
            material_deltas=material_deltas,
            availability_events=availability,
            schema_version=payload.get("schema_version", 0),
            profile=payload.get("profile", ""),
        )
    except CatalystEvidenceError:
        raise
    except (TypeError, ValueError) as exc:
        raise CatalystEvidenceError("Catalyst ledger payload is malformed.") from exc


def revision_fingerprint_payload(revision: CatalystRevision) -> dict[str, object]:
    payload = asdict(revision)
    payload.pop("fingerprint")
    return payload


def material_delta_fingerprint_payload(
    delta: CatalystMaterialDeltaEvent,
) -> dict[str, object]:
    payload = asdict(delta)
    payload.pop("fingerprint")
    payload.pop("delta_id")
    return payload


def availability_fingerprint_payload(
    event: CatalystAvailabilityEvent,
) -> dict[str, object]:
    payload = asdict(event)
    payload.pop("fingerprint")
    return payload


def _validate_source_chain(
    previous: CatalystRevision,
    observation: CatalystObservation,
) -> None:
    if (
        previous.source_identity != observation.source_identity
        or previous.source_article_id != observation.source_article_id
        or previous.provider != observation.provider
        or previous.source_name != observation.source_name
        or previous.candidate_symbol != observation.candidate_symbol
    ):
        raise CatalystEvidenceError(
            "Catalyst source article chain changed its stable identity."
        )


def _latest_availability(
    ledger: CatalystEvidenceLedger,
    source_identity: str,
    evaluated_at: datetime,
) -> CatalystAvailabilityEvent | None:
    eligible = [
        item
        for item in ledger.availability_events
        if item.source_identity == source_identity
        and _timestamp(item.occurred_at, "Availability timestamp") <= evaluated_at
    ]
    return eligible[-1] if eligible else None


def _source_is_out(
    ledger: CatalystEvidenceLedger,
    source_identity: str,
    evaluated_at: datetime | None,
) -> bool:
    events = [
        item
        for item in ledger.availability_events
        if item.source_identity == source_identity
        and (
            evaluated_at is None
            or _timestamp(item.occurred_at, "Availability timestamp") <= evaluated_at
        )
    ]
    return bool(events and events[-1].status == OUTAGE)


def fingerprint_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


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
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CatalystEvidenceError(f"{name} is invalid.")
    text = value.strip()
    if not _IDENTITY.fullmatch(text):
        raise CatalystEvidenceError(f"{name} is invalid.")
    return text


def _sha256(value: object, name: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256.fullmatch(text):
        raise CatalystEvidenceError(f"{name} is invalid.")
    return text


def _symbol(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CatalystEvidenceError(f"{name} is invalid.")
    text = value.strip().upper()
    if not _SYMBOL.fullmatch(text):
        raise CatalystEvidenceError(f"{name} is invalid.")
    return text


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CatalystEvidenceError(f"{name} is required.")
    text = " ".join(value.split())
    if not text:
        raise CatalystEvidenceError(f"{name} is required.")
    return text


def _optional_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalystEvidenceError(f"{name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CatalystEvidenceError(f"{name} must include a timezone.")
    return parsed


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CatalystEvidenceError(f"{name} must include a timezone.")
    return value


def _iso(value: datetime) -> str:
    return value.isoformat()
