"""Append-only readiness and composition attempt chronology."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.continuous_time_identity import (
    canonical_instant,
    canonical_known_at,
    parse_instant,
)


ATTEMPT_STARTED = "ATTEMPT_STARTED"
ATTEMPT_SUCCEEDED = "ATTEMPT_SUCCEEDED"
ATTEMPT_FAILED = "ATTEMPT_FAILED"
ATTEMPT_EVENTS = frozenset(
    {ATTEMPT_STARTED, ATTEMPT_SUCCEEDED, ATTEMPT_FAILED}
)
ATTEMPT_STAGES = frozenset({"READINESS", "COMPOSITION"})


class ContinuousAttemptLedgerError(RuntimeError):
    """Raised when attempt chronology is conflicting, corrupt, or incomplete."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


@dataclass(frozen=True)
class AttemptEvent:
    schema_version: int
    sequence: int
    event_id: str
    predecessor_event_id: str | None
    runtime_identity: str
    runtime_instance_id: str
    process_id: int
    configuration_fingerprint: str
    attempt_id: str
    attempt_number: int
    event_type: str
    stage: str
    symbol: str
    opportunity_id: str
    request_id: str
    attempt_started_at: str
    observed_at: str
    original_request_cutoff: str
    canonical_request_cutoff: str
    original_evidence_known_at: tuple[tuple[str, str], ...]
    canonical_evidence_known_at: tuple[tuple[str, str], ...]
    source_fingerprint: str
    predecessor_lifecycle_identity: str
    current_lifecycle_identity: str
    diagnostic_code: str
    exception_class: str
    message: str
    staging_began: bool
    authoritative_state_changed: bool
    fingerprint: str


class ContinuousAttemptLedger:
    """Write-once event ledger reconstructed and verified on every restart."""

    def __init__(
        self,
        root: Path,
        *,
        runtime_identity: str,
        configuration_fingerprint: str,
    ) -> None:
        self.root = root.resolve(strict=False)
        self.runtime_identity = str(runtime_identity).strip()
        if not self.runtime_identity:
            raise ContinuousAttemptLedgerError("Attempt ledger runtime identity is required.")
        self.configuration_fingerprint = str(configuration_fingerprint)
        if len(self.configuration_fingerprint) != 64:
            raise ContinuousAttemptLedgerError(
                "Attempt ledger configuration fingerprint is invalid."
            )
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "attempt-events.jsonl"
        self._events = self._load()
        self._event_by_id = {event.event_id: event for event in self._events}
        self._attempt_counts: dict[tuple[str, str], int] = {}
        for event in self._events:
            if event.event_type == ATTEMPT_STARTED:
                key = (event.stage, event.request_id)
                self._attempt_counts[key] = self._attempt_counts.get(key, 0) + 1

    @property
    def events(self) -> tuple[AttemptEvent, ...]:
        return self._events

    def next_attempt_number(self, *, stage: str, request_id: str) -> int:
        return self._attempt_counts.get((stage, request_id), 0) + 1

    def begin(
        self,
        *,
        runtime_instance_id: str,
        stage: str,
        symbol: str,
        opportunity_id: str,
        request_id: str,
        observed_at: str,
        request_cutoff: str,
        evidence_known_at: Iterable[tuple[str, str]],
        source_fingerprint: str,
        staging_began: bool,
    ) -> AttemptEvent:
        attempt_number = self.next_attempt_number(stage=stage, request_id=request_id)
        attempt_id = _fingerprint(
            "continuous-attempt-v1",
            {
                "runtimeIdentity": self.runtime_identity,
                "stage": stage,
                "requestId": request_id,
                "attemptNumber": attempt_number,
            },
        )
        return self._append(
            runtime_instance_id=runtime_instance_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            event_type=ATTEMPT_STARTED,
            stage=stage,
            symbol=symbol,
            opportunity_id=opportunity_id,
            request_id=request_id,
            attempt_started_at=observed_at,
            observed_at=observed_at,
            request_cutoff=request_cutoff,
            evidence_known_at=evidence_known_at,
            source_fingerprint=source_fingerprint,
            predecessor_lifecycle_identity="",
            current_lifecycle_identity="",
            diagnostic_code="",
            exception_class="",
            message="",
            staging_began=staging_began,
            authoritative_state_changed=False,
        )

    def finish(
        self,
        started: AttemptEvent,
        *,
        runtime_instance_id: str,
        event_type: str,
        observed_at: str,
        diagnostic_code: str = "",
        exception_class: str = "",
        message: str = "",
        predecessor_lifecycle_identity: str = "",
        current_lifecycle_identity: str = "",
        opportunity_id: str | None = None,
        request_cutoff: str | None = None,
        evidence_known_at: Iterable[tuple[str, str]] | None = None,
        staging_began: bool | None = None,
        authoritative_state_changed: bool,
    ) -> AttemptEvent:
        if started.event_type != ATTEMPT_STARTED:
            raise ContinuousAttemptLedgerError(
                "Attempt completion does not reference a start event."
            )
        return self._append(
            runtime_instance_id=runtime_instance_id,
            attempt_id=started.attempt_id,
            attempt_number=started.attempt_number,
            event_type=event_type,
            stage=started.stage,
            symbol=started.symbol,
            opportunity_id=(
                started.opportunity_id if opportunity_id is None else opportunity_id
            ),
            request_id=started.request_id,
            attempt_started_at=started.attempt_started_at,
            observed_at=observed_at,
            request_cutoff=(
                started.original_request_cutoff
                if request_cutoff is None
                else request_cutoff
            ),
            evidence_known_at=(
                started.original_evidence_known_at
                if evidence_known_at is None
                else evidence_known_at
            ),
            source_fingerprint=started.source_fingerprint,
            predecessor_lifecycle_identity=predecessor_lifecycle_identity,
            current_lifecycle_identity=current_lifecycle_identity,
            diagnostic_code=diagnostic_code,
            exception_class=exception_class,
            message=message,
            staging_began=(started.staging_began if staging_began is None else staging_began),
            authoritative_state_changed=authoritative_state_changed,
        )

    def _append(
        self,
        *,
        runtime_instance_id: str,
        attempt_id: str,
        attempt_number: int,
        event_type: str,
        stage: str,
        symbol: str,
        opportunity_id: str,
        request_id: str,
        attempt_started_at: str,
        observed_at: str,
        request_cutoff: str,
        evidence_known_at: Iterable[tuple[str, str]],
        source_fingerprint: str,
        predecessor_lifecycle_identity: str,
        current_lifecycle_identity: str,
        diagnostic_code: str,
        exception_class: str,
        message: str,
        staging_began: bool,
        authoritative_state_changed: bool,
    ) -> AttemptEvent:
        if event_type not in ATTEMPT_EVENTS or stage not in ATTEMPT_STAGES:
            raise ContinuousAttemptLedgerError("Attempt event type or stage is invalid.")
        original_known_at = tuple(
            (str(name), str(value)) for name, value in evidence_known_at
        )
        canonical_cutoff = canonical_instant(request_cutoff, "Attempt request cutoff")
        canonical_chronology = canonical_known_at(original_known_at)
        cutoff_instant = parse_instant(canonical_cutoff)
        if any(parse_instant(value) > cutoff_instant for _, value in canonical_chronology):
            raise ContinuousAttemptLedgerError(
                "Attempt evidence became known after its decision cutoff."
            )
        values = {
            "schema_version": 1,
            "sequence": len(self._events) + 1,
            "predecessor_event_id": (
                self._events[-1].event_id if self._events else None
            ),
            "runtime_identity": self.runtime_identity,
            "runtime_instance_id": str(runtime_instance_id),
            "process_id": os.getpid(),
            "configuration_fingerprint": self.configuration_fingerprint,
            "attempt_id": attempt_id,
            "attempt_number": int(attempt_number),
            "event_type": event_type,
            "stage": stage,
            "symbol": str(symbol).strip().upper(),
            "opportunity_id": str(opportunity_id),
            "request_id": str(request_id),
            "attempt_started_at": canonical_instant(
                attempt_started_at, "Attempt start time"
            ),
            "observed_at": canonical_instant(observed_at, "Attempt observation time"),
            "original_request_cutoff": str(request_cutoff),
            "canonical_request_cutoff": canonical_cutoff,
            "original_evidence_known_at": original_known_at,
            "canonical_evidence_known_at": canonical_chronology,
            "source_fingerprint": str(source_fingerprint),
            "predecessor_lifecycle_identity": str(
                predecessor_lifecycle_identity
            ),
            "current_lifecycle_identity": str(current_lifecycle_identity),
            "diagnostic_code": str(diagnostic_code),
            "exception_class": str(exception_class),
            "message": str(message)[:4000],
            "staging_began": bool(staging_began),
            "authoritative_state_changed": bool(authoritative_state_changed),
        }
        event_id = _fingerprint(
            "continuous-attempt-event-id-v1",
            {"attemptId": attempt_id, "eventType": event_type},
        )
        payload = {**values, "event_id": event_id}
        fingerprint = _fingerprint("continuous-attempt-event-v1", payload)
        event = AttemptEvent(**payload, fingerprint=fingerprint)
        existing = self._event_by_id.get(event_id)
        if existing is not None:
            if existing != event:
                raise ContinuousAttemptLedgerError(
                    "Attempt event identity was reused with conflicting evidence."
                )
            return existing
        with self.path.open("ab") as handle:
            handle.write(_canonical_bytes(asdict(event)))
            handle.flush()
            os.fsync(handle.fileno())
        self._events = (*self._events, event)
        self._event_by_id[event.event_id] = event
        if event.event_type == ATTEMPT_STARTED:
            key = (event.stage, event.request_id)
            self._attempt_counts[key] = self._attempt_counts.get(key, 0) + 1
        return event

    def _load(self) -> tuple[AttemptEvent, ...]:
        if not self.path.exists():
            return ()
        events: list[AttemptEvent] = []
        event_ids: set[str] = set()
        try:
            lines = self.path.read_bytes().splitlines(keepends=True)
        except OSError as exc:
            raise ContinuousAttemptLedgerError(
                "Attempt ledger is unreadable."
            ) from exc
        for index, line in enumerate(lines, start=1):
            if not line.endswith(b"\n"):
                raise ContinuousAttemptLedgerError(
                    "Attempt ledger contains an incomplete terminal record."
                )
            try:
                payload = json.loads(line.decode("ascii"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ContinuousAttemptLedgerError(
                    f"Attempt ledger record {index} is unreadable."
                ) from exc
            if not isinstance(payload, Mapping):
                raise ContinuousAttemptLedgerError("Attempt ledger record is invalid.")
            normalized = dict(payload)
            fingerprint = str(normalized.pop("fingerprint", ""))
            expected = _fingerprint("continuous-attempt-event-v1", normalized)
            if fingerprint != expected:
                raise ContinuousAttemptLedgerError(
                    f"Attempt ledger fingerprint is invalid at sequence {index}."
                )
            normalized["original_evidence_known_at"] = tuple(
                tuple(item)
                for item in normalized.get("original_evidence_known_at", ())
            )
            normalized["canonical_evidence_known_at"] = tuple(
                tuple(item)
                for item in normalized.get("canonical_evidence_known_at", ())
            )
            event = AttemptEvent(**normalized, fingerprint=fingerprint)
            if event.runtime_identity != self.runtime_identity:
                raise ContinuousAttemptLedgerError(
                    "Attempt ledger runtime identity changed."
                )
            if event.configuration_fingerprint != self.configuration_fingerprint:
                raise ContinuousAttemptLedgerError(
                    "Attempt ledger configuration identity changed."
                )
            if event.sequence != len(events) + 1:
                raise ContinuousAttemptLedgerError("Attempt ledger sequence is not contiguous.")
            predecessor = events[-1].event_id if events else None
            if event.predecessor_event_id != predecessor:
                raise ContinuousAttemptLedgerError(
                    "Attempt ledger predecessor chain is invalid."
                )
            if event.event_id in event_ids:
                raise ContinuousAttemptLedgerError("Attempt ledger event is duplicated.")
            event_ids.add(event.event_id)
            events.append(event)
        return tuple(events)
