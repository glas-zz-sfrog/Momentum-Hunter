"""Dormant runtime-source admission for continuous decision cycles.

Every new continuous plan version selects exactly one upstream source. Candidate
lifecycle changes retain their exact event identity. All other evidence changes
must be consolidated into the immutable successor plan before they can trigger
another cycle. Persistence is limited to a caller-selected append-only evidence
path. This module performs no discovery, provider work, risk, allocation,
selection, or execution.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterator, Mapping

from momentum_hunter.candidate_lifecycle import (
    DATA_RECOVERED_EVENT,
    DATA_STALE_EVENT,
    DISCOVERY_EVENT,
    EVIDENCE_REFRESH_EVENT,
    STATE_TRANSITION_EVENT,
    CandidateLifecycleEvent,
    CandidateLifecycleLedger,
    validate_ledger as validate_candidate_ledger,
    validate_lifecycle_event,
)
from momentum_hunter.continuous_plan_version import (
    PLAN_BLOCKED,
    ContinuousPlanLedger,
    ContinuousPlanVersion,
    validate_ledger as validate_plan_ledger,
    validate_plan_version,
)
from momentum_hunter.event_driven_decision_cycle import (
    CANDIDATE_STATE_CHANGED,
    CONTINUOUS_PLAN_SOURCE_IDENTITY,
    DATA_BECAME_STALE,
    MATERIAL,
    PLAN_INVALIDATED,
    PLAN_MATERIAL_REVISION,
    DecisionTriggerEvidence,
    EventDecisionCyclePolicy,
    build_decision_trigger,
    canonical_json_bytes,
    fingerprint_payload,
    validate_policy,
    validate_trigger,
)
from momentum_hunter.path_transaction import (
    PathTransactionLease,
    PathTransactionLeaseError,
    PathTransactionLeaseTimeoutError,
)


RUNTIME_SOURCE_ADMISSION_SCHEMA_VERSION = 1
RUNTIME_SOURCE_ADMISSION_PROFILE = "runtime-decision-source-admission-v1"
RUNTIME_SOURCE_ADMISSION_LEDGER_SCHEMA_VERSION = 1
RUNTIME_SOURCE_ADMISSION_LEDGER_PROFILE = "runtime-source-admission-ledger-v1"

CANDIDATE_LIFECYCLE_SOURCE = "CANDIDATE_LIFECYCLE"
CONTINUOUS_PLAN_SOURCE = CONTINUOUS_PLAN_SOURCE_IDENTITY
RUNTIME_SOURCE_KINDS = frozenset(
    {CANDIDATE_LIFECYCLE_SOURCE, CONTINUOUS_PLAN_SOURCE}
)

EXACT_CANDIDATE_EVENT = "EXACT_CANDIDATE_LIFECYCLE_EVENT"
EXACT_PLAN_SUCCESSOR = "EXACT_CONTINUOUS_PLAN_SUCCESSOR"
CANDIDATE_REFRESH_THROUGH_PLAN = "CANDIDATE_REFRESH_THROUGH_PLAN_SUCCESSOR"
PLAN_SUCCESSOR_BLOCKED = "PLAN_SUCCESSOR_BLOCKED"

_SHA256 = re.compile(r"[0-9a-f]{64}")


class RuntimeSourceAdmissionError(ValueError):
    """Raised when a runtime trigger source is missing or contradictory."""


@dataclass(frozen=True)
class RuntimeSourceAdmission:
    admission_id: str
    source_kind: str
    source_record_id: str
    source_record_fingerprint: str
    source_authority_fingerprint: str
    plan_version_id: str
    plan_version_fingerprint: str
    predecessor_plan_version_id: str
    predecessor_plan_version_fingerprint: str
    event_cycle_policy_fingerprint: str
    reason: str
    trigger: DecisionTriggerEvidence
    schema_version: int = RUNTIME_SOURCE_ADMISSION_SCHEMA_VERSION
    profile: str = RUNTIME_SOURCE_ADMISSION_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeSourceAdmissionLedger:
    admissions: tuple[RuntimeSourceAdmission, ...] = ()
    schema_version: int = RUNTIME_SOURCE_ADMISSION_LEDGER_SCHEMA_VERSION
    profile: str = RUNTIME_SOURCE_ADMISSION_LEDGER_PROFILE


class RuntimeSourceAdmissionStore:
    """Append-only explicit-path store for admitted runtime trigger sources."""

    def __init__(self, path: Path, *, lease_timeout_seconds: float = 5.0) -> None:
        self.path = Path(path)
        try:
            self._transaction_lease = PathTransactionLease(
                self.path,
                timeout_seconds=lease_timeout_seconds,
            )
        except PathTransactionLeaseError as exc:
            raise RuntimeSourceAdmissionError(
                "Runtime source-admission lease timeout must be positive and finite."
            ) from exc
        self.lease_timeout_seconds = self._transaction_lease.timeout_seconds
        self.lease_path = self._transaction_lease.lease_path
        self._lock = self._transaction_lease.thread_lock

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            with self._transaction_lease.transaction():
                yield
        except PathTransactionLeaseTimeoutError as exc:
            raise RuntimeSourceAdmissionError(
                "Runtime source-admission ledger lease timed out."
            ) from exc

    def load(self) -> RuntimeSourceAdmissionLedger:
        with self._lock:
            if not self.path.exists():
                return RuntimeSourceAdmissionLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeSourceAdmissionError(
                    "Runtime source-admission ledger cannot be loaded: "
                    f"{type(exc).__name__}"
                ) from exc
            ledger = source_admission_ledger_from_wire(payload)
            validate_runtime_source_admission_ledger(ledger)
            return ledger

    def append(self, admission: RuntimeSourceAdmission) -> RuntimeSourceAdmission:
        validate_runtime_source_admission(admission)
        with self.transaction():
            ledger = self.load()
            for existing in ledger.admissions:
                if existing.admission_id == admission.admission_id:
                    if existing == admission:
                        return existing
                    raise RuntimeSourceAdmissionError(
                        "Runtime source admission identity was reused with conflicting evidence."
                    )
                if existing.plan_version_id == admission.plan_version_id:
                    raise RuntimeSourceAdmissionError(
                        "A plan version already has a different runtime source admission."
                    )
                if (
                    existing.source_kind,
                    existing.source_record_id,
                ) == (
                    admission.source_kind,
                    admission.source_record_id,
                ):
                    raise RuntimeSourceAdmissionError(
                        "A canonical source record already admitted a different plan version."
                    )
            updated = replace(
                ledger,
                admissions=ledger.admissions + (admission,),
            )
            validate_runtime_source_admission_ledger(updated)
            _atomic_write(
                self.path,
                canonical_json_bytes(source_admission_ledger_to_wire(updated)),
            )
            return admission


def admit_runtime_trigger_source(
    *,
    plan_version: ContinuousPlanVersion,
    plan_ledger: ContinuousPlanLedger,
    event_cycle_policy: EventDecisionCyclePolicy,
    previous_plan_version: ContinuousPlanVersion | None = None,
    candidate_event: CandidateLifecycleEvent | None = None,
    candidate_ledger: CandidateLifecycleLedger | None = None,
) -> RuntimeSourceAdmission:
    """Choose one exact source for one new continuous plan version."""

    validate_plan_version(plan_version)
    validate_policy(event_cycle_policy)
    if (
        event_cycle_policy.configuration_fingerprint
        != plan_version.configuration_fingerprint
    ):
        raise RuntimeSourceAdmissionError(
            "Runtime source policy does not match the plan configuration."
        )
    _validate_plan_lineage(plan_version, previous_plan_version)
    _validate_plan_membership(plan_ledger, plan_version, previous_plan_version)

    candidate_changed = previous_plan_version is None or (
        plan_version.candidate_event_id
        != previous_plan_version.candidate_event_id
    )
    if candidate_changed and candidate_event is None:
        raise RuntimeSourceAdmissionError(
            "A changed candidate identity requires its exact lifecycle event."
        )
    if not candidate_changed and candidate_event is not None:
        raise RuntimeSourceAdmissionError(
            "An unchanged candidate identity cannot claim a new lifecycle source."
        )

    if candidate_event is not None:
        if candidate_ledger is None:
            raise RuntimeSourceAdmissionError(
                "A candidate runtime source requires its canonical ledger."
            )
        _validate_candidate_membership(candidate_ledger, candidate_event)
        _validate_candidate_binding(candidate_event, plan_version)
        if candidate_event.event_type == DISCOVERY_EVENT:
            raise RuntimeSourceAdmissionError(
                "Candidate discovery cannot create a cycle before a setup-bound plan."
            )
        if candidate_event.event_type != EVIDENCE_REFRESH_EVENT:
            trigger_type = _candidate_trigger_type(candidate_event)
            return _build_admission(
                source_kind=CANDIDATE_LIFECYCLE_SOURCE,
                source_record_id=candidate_event.event_id,
                source_record_fingerprint=candidate_event.fingerprint,
                source_authority_fingerprint=candidate_event.evidence_fingerprint,
                plan_version=plan_version,
                previous_plan_version=previous_plan_version,
                event_cycle_policy=event_cycle_policy,
                reason=EXACT_CANDIDATE_EVENT,
                trigger=build_decision_trigger(
                    trigger_type=trigger_type,
                    opportunity_id=plan_version.opportunity_id,
                    setup_id=plan_version.setup_id,
                    symbol=plan_version.symbol,
                    session_date=plan_version.session_date,
                    previous_candidate_state=candidate_event.previous_state,
                    next_candidate_state=candidate_event.next_state,
                    occurred_at=_timestamp(
                        candidate_event.occurred_at, "Candidate event timestamp"
                    ),
                    provider_timestamp=_timestamp(
                        candidate_event.provider_timestamp,
                        "Candidate provider timestamp",
                    ),
                    receipt_timestamp=_timestamp(
                        candidate_event.receipt_timestamp,
                        "Candidate receipt timestamp",
                    ),
                    source_identity=candidate_event.source_identity,
                    source_evidence_id=candidate_event.event_id,
                    source_evidence_fingerprint=(
                        candidate_event.evidence_fingerprint
                    ),
                    material_delta_kind=candidate_event.material_delta_kind,
                    materiality=MATERIAL,
                    candidate_event_id=candidate_event.event_id,
                ),
            )
        if previous_plan_version is None:
            raise RuntimeSourceAdmissionError(
                "An initial plan cannot be sourced by an evidence refresh."
            )
        reason = CANDIDATE_REFRESH_THROUGH_PLAN
    else:
        became_blocked = (
            previous_plan_version is not None
            and plan_version.status == PLAN_BLOCKED
            and previous_plan_version.status != PLAN_BLOCKED
        )
        reason = (
            PLAN_SUCCESSOR_BLOCKED
            if became_blocked
            else EXACT_PLAN_SUCCESSOR
        )

    if previous_plan_version is None:
        raise RuntimeSourceAdmissionError(
            "A plan-version source requires an exact predecessor plan."
        )
    if not _material_plan_change(previous_plan_version, plan_version):
        raise RuntimeSourceAdmissionError(
            "A successor plan has no material authority or timing change."
        )
    became_blocked = (
        plan_version.status == PLAN_BLOCKED
        and previous_plan_version.status != PLAN_BLOCKED
    )
    trigger_type = PLAN_INVALIDATED if became_blocked else PLAN_MATERIAL_REVISION
    created_at = _timestamp(plan_version.created_at, "Plan creation timestamp")
    provider_timestamp = max(
        _timestamp(item.provider_timestamp, "Plan source provider timestamp")
        for item in plan_version.source_clocks
    )
    return _build_admission(
        source_kind=CONTINUOUS_PLAN_SOURCE,
        source_record_id=plan_version.plan_version_id,
        source_record_fingerprint=plan_version.fingerprint,
        source_authority_fingerprint=plan_version.fingerprint,
        plan_version=plan_version,
        previous_plan_version=previous_plan_version,
        event_cycle_policy=event_cycle_policy,
        reason=reason,
        trigger=build_decision_trigger(
            trigger_type=trigger_type,
            opportunity_id=plan_version.opportunity_id,
            setup_id=plan_version.setup_id,
            symbol=plan_version.symbol,
            session_date=plan_version.session_date,
            previous_candidate_state=previous_plan_version.candidate_state,
            next_candidate_state=plan_version.candidate_state,
            occurred_at=created_at,
            provider_timestamp=provider_timestamp,
            receipt_timestamp=created_at,
            source_identity=CONTINUOUS_PLAN_SOURCE_IDENTITY,
            source_evidence_id=plan_version.plan_version_id,
            source_evidence_fingerprint=plan_version.fingerprint,
            material_delta_kind=(
                "PLAN_BECAME_BLOCKED"
                if trigger_type == PLAN_INVALIDATED
                else "PLAN_VERSION_SUPERSEDED"
            ),
            materiality=MATERIAL,
        ),
    )


def validate_runtime_source_admission(admission: RuntimeSourceAdmission) -> None:
    if (
        admission.schema_version != RUNTIME_SOURCE_ADMISSION_SCHEMA_VERSION
        or admission.profile != RUNTIME_SOURCE_ADMISSION_PROFILE
    ):
        raise RuntimeSourceAdmissionError(
            "Runtime source admission schema identity is unsupported."
        )
    if admission.source_kind not in RUNTIME_SOURCE_KINDS:
        raise RuntimeSourceAdmissionError("Runtime source kind is unsupported.")
    for value, name in (
        (admission.source_record_id, "Source record identity"),
        (admission.plan_version_id, "Plan version identity"),
        (admission.reason, "Source admission reason"),
    ):
        _required_text(value, name)
    for value, name in (
        (admission.source_record_fingerprint, "Source record fingerprint"),
        (admission.source_authority_fingerprint, "Source authority fingerprint"),
        (admission.plan_version_fingerprint, "Plan version fingerprint"),
        (admission.event_cycle_policy_fingerprint, "Event-cycle policy fingerprint"),
    ):
        _sha256(value, name)
    if bool(admission.predecessor_plan_version_id) != bool(
        admission.predecessor_plan_version_fingerprint
    ):
        raise RuntimeSourceAdmissionError(
            "Source admission predecessor identity is incomplete."
        )
    if admission.predecessor_plan_version_fingerprint:
        _sha256(
            admission.predecessor_plan_version_fingerprint,
            "Predecessor plan fingerprint",
        )
    validate_trigger(admission.trigger)
    if admission.trigger.source_evidence_fingerprint != (
        admission.source_authority_fingerprint
    ):
        raise RuntimeSourceAdmissionError(
            "Trigger authority does not match the admitted source."
        )
    if admission.source_kind == CANDIDATE_LIFECYCLE_SOURCE:
        if (
            admission.source_record_id != admission.trigger.candidate_event_id
            or admission.source_record_id != admission.trigger.source_evidence_id
        ):
            raise RuntimeSourceAdmissionError(
                "Candidate source admission lost its event identity."
            )
    elif (
        admission.source_record_id != admission.plan_version_id
        or admission.source_record_fingerprint != admission.plan_version_fingerprint
        or admission.source_authority_fingerprint
        != admission.plan_version_fingerprint
        or admission.trigger.source_identity != CONTINUOUS_PLAN_SOURCE_IDENTITY
    ):
        raise RuntimeSourceAdmissionError(
            "Plan source admission lost its exact plan identity."
        )
    expected_id = _expected_admission_id(admission)
    if admission.admission_id != expected_id:
        raise RuntimeSourceAdmissionError("Runtime source admission identity is invalid.")
    if admission.fingerprint != admission_fingerprint(admission):
        raise RuntimeSourceAdmissionError(
            "Runtime source admission fingerprint is invalid."
        )


def admission_fingerprint(admission: RuntimeSourceAdmission) -> str:
    return fingerprint_payload(asdict(replace(admission, fingerprint="")))


def validate_runtime_source_admission_ledger(
    ledger: RuntimeSourceAdmissionLedger,
) -> None:
    if (
        ledger.schema_version != RUNTIME_SOURCE_ADMISSION_LEDGER_SCHEMA_VERSION
        or ledger.profile != RUNTIME_SOURCE_ADMISSION_LEDGER_PROFILE
    ):
        raise RuntimeSourceAdmissionError(
            "Runtime source-admission ledger schema identity is unsupported."
        )

    by_admission_id: dict[str, RuntimeSourceAdmission] = {}
    by_plan_id: dict[str, RuntimeSourceAdmission] = {}
    by_source: dict[tuple[str, str], RuntimeSourceAdmission] = {}
    opportunity_roots: set[str] = set()
    for admission in ledger.admissions:
        validate_runtime_source_admission(admission)
        if admission.admission_id in by_admission_id:
            raise RuntimeSourceAdmissionError(
                "Runtime source-admission ledger contains a duplicate identity."
            )
        if admission.plan_version_id in by_plan_id:
            raise RuntimeSourceAdmissionError(
                "Runtime source-admission ledger contains multiple sources for one plan."
            )
        source_key = (admission.source_kind, admission.source_record_id)
        if source_key in by_source:
            raise RuntimeSourceAdmissionError(
                "Runtime source-admission ledger reuses one canonical source record."
            )

        predecessor_id = admission.predecessor_plan_version_id
        if predecessor_id:
            predecessor = by_plan_id.get(predecessor_id)
            if predecessor is None:
                raise RuntimeSourceAdmissionError(
                    "Runtime source-admission ledger has an orphan or out-of-order predecessor."
                )
            if (
                predecessor.plan_version_fingerprint
                != admission.predecessor_plan_version_fingerprint
            ):
                raise RuntimeSourceAdmissionError(
                    "Runtime source-admission predecessor fingerprint is contradictory."
                )
            if (
                predecessor.trigger.opportunity_id,
                predecessor.trigger.symbol,
                predecessor.trigger.session_date,
            ) != (
                admission.trigger.opportunity_id,
                admission.trigger.symbol,
                admission.trigger.session_date,
            ):
                raise RuntimeSourceAdmissionError(
                    "Runtime source-admission predecessor changed opportunity identity."
                )
            if _timestamp(
                admission.trigger.receipt_timestamp,
                "Source-admission trigger receipt timestamp",
            ) < _timestamp(
                predecessor.trigger.receipt_timestamp,
                "Predecessor trigger receipt timestamp",
            ):
                raise RuntimeSourceAdmissionError(
                    "Runtime source-admission ledger regressed trigger chronology."
                )
        else:
            opportunity_id = admission.trigger.opportunity_id
            if opportunity_id in opportunity_roots:
                raise RuntimeSourceAdmissionError(
                    "An opportunity has multiple initial runtime source admissions."
                )
            opportunity_roots.add(opportunity_id)

        by_admission_id[admission.admission_id] = admission
        by_plan_id[admission.plan_version_id] = admission
        by_source[source_key] = admission


def source_admission_ledger_to_wire(
    ledger: RuntimeSourceAdmissionLedger,
) -> dict[str, object]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "admissions": [asdict(item) for item in ledger.admissions],
    }


def source_admission_ledger_from_wire(
    payload: object,
) -> RuntimeSourceAdmissionLedger:
    if not isinstance(payload, Mapping):
        raise RuntimeSourceAdmissionError(
            "Runtime source-admission ledger has an invalid shape."
        )
    admissions = payload.get("admissions")
    if not isinstance(admissions, list):
        raise RuntimeSourceAdmissionError(
            "Runtime source-admission ledger has an invalid schema."
        )
    try:
        parsed = []
        for item in admissions:
            if not isinstance(item, Mapping):
                raise TypeError("Malformed source admission")
            values = dict(item)
            trigger = values.get("trigger")
            if not isinstance(trigger, Mapping):
                raise TypeError("Malformed source-admission trigger")
            values["trigger"] = DecisionTriggerEvidence(**dict(trigger))
            parsed.append(RuntimeSourceAdmission(**values))
        ledger = RuntimeSourceAdmissionLedger(
            schema_version=int(payload.get("schema_version", 0)),
            profile=str(payload.get("profile", "")),
            admissions=tuple(parsed),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeSourceAdmissionError(
            "Runtime source-admission ledger contains an invalid record."
        ) from exc
    return ledger


def _build_admission(
    *,
    source_kind: str,
    source_record_id: str,
    source_record_fingerprint: str,
    source_authority_fingerprint: str,
    plan_version: ContinuousPlanVersion,
    previous_plan_version: ContinuousPlanVersion | None,
    event_cycle_policy: EventDecisionCyclePolicy,
    reason: str,
    trigger: DecisionTriggerEvidence,
) -> RuntimeSourceAdmission:
    if trigger.trigger_type not in event_cycle_policy.allowed_trigger_types:
        raise RuntimeSourceAdmissionError(
            "Event-cycle policy does not admit the derived runtime trigger."
        )
    provisional = RuntimeSourceAdmission(
        admission_id="",
        source_kind=source_kind,
        source_record_id=source_record_id,
        source_record_fingerprint=source_record_fingerprint,
        source_authority_fingerprint=source_authority_fingerprint,
        plan_version_id=plan_version.plan_version_id,
        plan_version_fingerprint=plan_version.fingerprint,
        predecessor_plan_version_id=(
            previous_plan_version.plan_version_id if previous_plan_version else ""
        ),
        predecessor_plan_version_fingerprint=(
            previous_plan_version.fingerprint if previous_plan_version else ""
        ),
        event_cycle_policy_fingerprint=event_cycle_policy.fingerprint,
        reason=reason,
        trigger=trigger,
    )
    with_identity = replace(
        provisional,
        admission_id=_expected_admission_id(provisional),
    )
    result = replace(with_identity, fingerprint=admission_fingerprint(with_identity))
    validate_runtime_source_admission(result)
    return result


def _expected_admission_id(admission: RuntimeSourceAdmission) -> str:
    payload = asdict(replace(admission, admission_id="", fingerprint=""))
    identity = fingerprint_payload(payload)
    return f"runtime-source-admission-{identity[:24]}"


def _validate_plan_lineage(
    plan: ContinuousPlanVersion,
    previous: ContinuousPlanVersion | None,
) -> None:
    if previous is None:
        if (
            plan.version_number != 1
            or plan.predecessor_plan_version_id
            or plan.predecessor_plan_version_fingerprint
        ):
            raise RuntimeSourceAdmissionError(
                "A successor plan requires its exact predecessor."
            )
        return
    validate_plan_version(previous)
    if (
        plan.version_number != previous.version_number + 1
        or plan.predecessor_plan_version_id != previous.plan_version_id
        or plan.predecessor_plan_version_fingerprint != previous.fingerprint
    ):
        raise RuntimeSourceAdmissionError(
            "Runtime plan source does not extend the exact predecessor."
        )
    if (
        plan.opportunity_id,
        plan.symbol,
        plan.session_date,
    ) != (
        previous.opportunity_id,
        previous.symbol,
        previous.session_date,
    ):
        raise RuntimeSourceAdmissionError(
            "A runtime plan successor changed opportunity identity."
        )
    if plan.candidate_event_id == previous.candidate_event_id and (
        plan.candidate_evidence_fingerprint,
        plan.candidate_policy_fingerprint,
        plan.candidate_state,
        plan.candidate_updated_at,
    ) != (
        previous.candidate_evidence_fingerprint,
        previous.candidate_policy_fingerprint,
        previous.candidate_state,
        previous.candidate_updated_at,
    ):
        raise RuntimeSourceAdmissionError(
            "Candidate evidence changed without a new lifecycle event identity."
        )
    if _timestamp(plan.created_at, "Plan creation timestamp") <= _timestamp(
        previous.created_at, "Previous plan creation timestamp"
    ):
        raise RuntimeSourceAdmissionError(
            "A runtime plan successor did not advance chronology."
        )


def _validate_plan_membership(
    ledger: ContinuousPlanLedger,
    plan: ContinuousPlanVersion,
    previous: ContinuousPlanVersion | None,
) -> None:
    validate_plan_ledger(ledger)
    stored = next(
        (item for item in ledger.plans if item.plan_version_id == plan.plan_version_id),
        None,
    )
    if stored != plan:
        raise RuntimeSourceAdmissionError(
            "Runtime plan source is not the exact canonical ledger record."
        )
    if previous is not None:
        stored_previous = next(
            (
                item
                for item in ledger.plans
                if item.plan_version_id == previous.plan_version_id
            ),
            None,
        )
        if stored_previous != previous:
            raise RuntimeSourceAdmissionError(
                "Runtime predecessor is not the exact canonical ledger record."
            )


def _validate_candidate_membership(
    ledger: CandidateLifecycleLedger,
    event: CandidateLifecycleEvent,
) -> None:
    validate_candidate_ledger(ledger)
    stored = next(
        (item for item in ledger.events if item.event_id == event.event_id),
        None,
    )
    if stored != event:
        raise RuntimeSourceAdmissionError(
            "Runtime candidate source is not the exact canonical ledger record."
        )


def _validate_candidate_binding(
    event: CandidateLifecycleEvent,
    plan: ContinuousPlanVersion,
) -> None:
    validate_lifecycle_event(event)
    if (
        event.event_id != plan.candidate_event_id
        or event.evidence_fingerprint != plan.candidate_evidence_fingerprint
        or event.policy_fingerprint != plan.candidate_policy_fingerprint
    ):
        raise RuntimeSourceAdmissionError(
            "Candidate source does not match the plan's frozen candidate evidence."
        )
    if (event.opportunity_id, event.symbol, event.session_date) != (
        plan.opportunity_id,
        plan.symbol,
        plan.session_date,
    ):
        raise RuntimeSourceAdmissionError(
            "Candidate source does not match the plan opportunity."
        )
    if event.next_state != plan.candidate_state:
        raise RuntimeSourceAdmissionError(
            "Candidate source state does not match the plan."
        )
    if event.event_type != DISCOVERY_EVENT and not event.setup_id:
        raise RuntimeSourceAdmissionError(
            "A runtime candidate source must be setup-bound."
        )
    if event.setup_id and (
        event.setup_id != plan.setup_id
        or event.setup_family != plan.setup_family
        or event.setup_sequence != plan.setup_sequence
    ):
        raise RuntimeSourceAdmissionError(
            "Candidate source setup does not match the plan."
        )
    if _timestamp(event.receipt_timestamp, "Candidate receipt timestamp") > _timestamp(
        plan.created_at, "Plan creation timestamp"
    ):
        raise RuntimeSourceAdmissionError(
            "Candidate source was received after plan creation."
        )


def _candidate_trigger_type(event: CandidateLifecycleEvent) -> str:
    if event.event_type == DATA_STALE_EVENT:
        return DATA_BECAME_STALE
    if event.event_type in {STATE_TRANSITION_EVENT, DATA_RECOVERED_EVENT}:
        return CANDIDATE_STATE_CHANGED
    raise RuntimeSourceAdmissionError(
        "Candidate lifecycle event type is not a runtime cycle source."
    )


def _material_plan_change(
    previous: ContinuousPlanVersion,
    current: ContinuousPlanVersion,
) -> bool:
    fields = (
        "setup_id",
        "setup_revision_id",
        "setup_revision_fingerprint",
        "setup_authority",
        "setup_driver",
        "intraday_plan_id",
        "intraday_plan_fingerprint",
        "intraday_plan_execution_eligible",
        "entry_expires_at",
        "forced_flat_at",
        "candidate_state",
        "candidate_event_id",
        "candidate_evidence_fingerprint",
        "regime_snapshot_id",
        "regime_snapshot_fingerprint",
        "regime_context_fingerprint",
        "regime_label",
        "regime_sufficiency",
        "event_context_id",
        "event_context_fingerprint",
        "event_status",
        "catalyst_snapshot_id",
        "catalyst_snapshot_fingerprint",
        "catalyst_revision_id",
        "catalyst_revision_fingerprint",
        "catalyst_authority",
        "catalyst_state",
        "catalyst_availability_status",
        "catalyst_is_duplicate",
        "rvol_evidence_id",
        "rvol_evidence_fingerprint",
        "rvol_authority_state",
        "source_clock_fingerprint",
        "status",
        "blockers",
        "warnings",
    )
    return any(getattr(previous, name) != getattr(current, name) for name in fields)


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RuntimeSourceAdmissionError(f"{name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeSourceAdmissionError(f"{name} must be timezone-aware.")
    return parsed


def _required_text(value: object, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise RuntimeSourceAdmissionError(f"{name} is required.")
    return normalized


def _sha256(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise RuntimeSourceAdmissionError(f"{name} must be SHA-256.")
    return normalized


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
