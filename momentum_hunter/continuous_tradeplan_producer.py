"""Bounded prospective TradePlan production for the Continuous research runtime.

The producer orchestrates existing canonical history, RVOL, candidate-lifecycle,
composition, and DATA-004 contracts.  It does not discover setup levels, contact
an account or broker, or expose order capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from momentum_hunter.automatic_candle_backfill import (
    ACTIVE_STATES,
    AutomaticCandleBackfillCoordinator,
)
from momentum_hunter.canonical_candle_evidence import (
    load_canonical_minute_finality_as_of,
)
from momentum_hunter.candidate_lifecycle import expected_opportunity_id, expected_setup_id
from momentum_hunter.continuous_composition import (
    CanonicalEvidenceInput,
    CompositionMemberInput,
    ContinuousCompositionCycle,
    ContinuousCompositionMemberResult,
    ContinuousCompositionPolicy,
    compose_cycle,
)
from momentum_hunter.hot_universe import HotUniverseMember, HotUniverseState
from momentum_hunter.lifecycle_position_identity import (
    LifecyclePositionIdentityError,
    authoritative_lifecycle_identity_from_report_row,
    bind_report_row_to_producer_identity,
)
from momentum_hunter.path_transaction import PathTransactionLease
from momentum_hunter.schwab_candle_contract import EASTERN_TZ
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore


PRODUCER_SCHEMA_VERSION = 2
PRODUCER_PROFILE = "continuous-prospective-tradeplan-producer-v1"
PRODUCER_VERSION = "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001D-v1"
RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "NONE"
ORDER_CAPABILITY_UNAVAILABLE = "UNAVAILABLE"

HISTORY_READY = "READY"
HISTORY_INSUFFICIENT = "INSUFFICIENT"
HISTORY_BACKFILL_PENDING = "BACKFILL_PENDING"
HISTORY_FAILED = "FAILED"
HISTORY_STATES = frozenset(
    {HISTORY_READY, HISTORY_INSUFFICIENT, HISTORY_BACKFILL_PENDING, HISTORY_FAILED}
)

COMMON_STOCK = "COMMON_STOCK"
ORDINARY_ETF = "ORDINARY_ETF"
LEVERAGED_ETP = "LEVERAGED_ETP"
INVERSE_ETP = "INVERSE_ETP"
ETN = "ETN"
UNKNOWN_INSTRUMENT = "UNKNOWN"
INSTRUMENT_CLASSES = frozenset(
    {
        COMMON_STOCK,
        ORDINARY_ETF,
        LEVERAGED_ETP,
        INVERSE_ETP,
        ETN,
        UNKNOWN_INSTRUMENT,
    }
)
EXECUTION_ELIGIBLE_INSTRUMENTS = frozenset({COMMON_STOCK, ORDINARY_ETF})
INSTRUMENT_ADMISSION_GAP = "AUTHORITATIVE_SUBTYPE_AND_LEVERAGE_CLASSIFICATION_UNAVAILABLE"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_RECORDS = 4_096
_MAX_STATE_BYTES = 64 * 1024 * 1024


class ContinuousTradePlanProducerError(ValueError):
    """Raised when producer evidence is incomplete, contradictory, or tampered."""


class ContinuousEvidenceChronologyError(ContinuousTradePlanProducerError):
    """Preserves the exact cutoff and known-at packet for chronology failures."""

    def __init__(
        self,
        diagnostic_code: str,
        message: str,
        *,
        request_cutoff: str,
        evidence_known_at: tuple[tuple[str, str], ...],
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.request_cutoff = request_cutoff
        self.evidence_known_at = evidence_known_at


class CurrentEvidenceLoader(Protocol):
    def __call__(self, symbol: str, cutoff: datetime) -> "CurrentMarketEvidence": ...


@dataclass(frozen=True)
class CurrentMarketEvidence:
    evidence_id: str
    symbol: str
    provider_timestamp: str
    receipt_timestamp: str
    source_identity: str
    market_payload_json: str
    market_payload_fingerprint: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class InstrumentAdmissionEvidence:
    evidence_id: str
    symbol: str
    observed_at: str
    source_identity: str
    instrument_class: str
    authoritative: bool
    evidence_fingerprint: str

    @property
    def execution_eligible(self) -> bool:
        return self.authoritative and self.instrument_class in EXECUTION_ELIGIBLE_INSTRUMENTS

    @property
    def blocker(self) -> str:
        if not self.authoritative or self.instrument_class == UNKNOWN_INSTRUMENT:
            return "INSTRUMENT_CLASSIFICATION_UNAVAILABLE"
        if self.instrument_class in {LEVERAGED_ETP, INVERSE_ETP, ETN}:
            return f"INSTRUMENT_CLASS_BLOCKED:{self.instrument_class}"
        return ""


@dataclass(frozen=True)
class HistoricalContextEvidence:
    context_id: str
    symbol: str
    session_date: str
    evidence_cutoff: str
    earliest_completed_minute: str
    latest_completed_minute: str
    minute_bar_count: int
    minute_session_count: int
    current_session_bar_count: int
    daily_bar_count: int
    minute_source_identity: str
    daily_source_identity: str
    minute_evidence_fingerprint: str
    daily_evidence_fingerprint: str
    content_fingerprint: str
    status: str
    blockers: tuple[str, ...]
    observed_provisional_version_count: int
    admitted_provisional_bar_count: int
    backfill_status: str
    fingerprint: str

    @property
    def provisional_bar_count(self) -> int:
        """Backward-compatible diagnostic alias; never decision-authoritative."""

        return self.observed_provisional_version_count


@dataclass(frozen=True)
class HistoryAdmissionResult:
    context: HistoricalContextEvidence
    canonical_evidence: CanonicalEvidenceInput | None
    current_market_evidence: CurrentMarketEvidence
    backfill_evidence: Mapping[str, object] | None
    current_collection_started_before_backfill_admission: bool
    decision_cutoff: str
    evidence_known_at: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ContinuousProducerRecord:
    record_id: str
    member_id: str
    symbol: str
    session_date: str
    candidate_origin_identity: str
    setup_id: str
    predecessor_setup_id: str
    evidence_cutoff: str
    historical_context_id: str
    historical_context_fingerprint: str
    current_market_evidence_id: str
    current_market_evidence_fingerprint: str
    instrument_admission_id: str
    instrument_admission_fingerprint: str
    material_evidence_fingerprint: str
    configuration_fingerprint: str
    composition_policy_fingerprint: str
    producer_version: str
    producer_fingerprint: str
    composition_cycle_id: str
    composition_cycle_fingerprint: str
    trade_plan_id: str
    trade_plan_fingerprint: str
    created_at: str
    entry_expires_at: str
    lifecycle_state: str
    execution_eligible: bool
    blockers: tuple[str, ...]
    payload_json: str
    payload_fingerprint: str
    schema_version: int = PRODUCER_SCHEMA_VERSION
    profile: str = PRODUCER_PROFILE
    fingerprint: str = ""
    opportunity_id: str = ""


@dataclass(frozen=True)
class ContinuousProducerEvaluation:
    record: ContinuousProducerRecord
    cycle: ContinuousCompositionCycle | None
    member_result: ContinuousCompositionMemberResult | None
    duplicate: bool

    @property
    def report_row(self) -> dict[str, object] | None:
        return producer_bound_report_row(self.record)


class ContinuousTradePlanProducerStore:
    """Bounded operational restart cache; durable evidence remains writer-owned."""

    def __init__(self, path: Path, *, lease_timeout_seconds: float = 5.0) -> None:
        self.path = Path(path)
        self.lease = PathTransactionLease(
            self.path, timeout_seconds=lease_timeout_seconds
        )

    def load(self) -> tuple[ContinuousProducerRecord, ...]:
        with self.lease.transaction():
            return self._load_unlocked()

    def append(self, record: ContinuousProducerRecord) -> ContinuousProducerRecord:
        validate_producer_record(record)
        with self.lease.transaction():
            records = list(self._load_unlocked())
            by_id = {item.record_id: item for item in records}
            existing = by_id.get(record.record_id)
            if existing is not None:
                if existing != record:
                    raise ContinuousTradePlanProducerError(
                        "Continuous producer identity was reused with conflicting evidence."
                    )
                return existing
            prior_material = next(
                (
                    item
                    for item in reversed(records)
                    if item.member_id == record.member_id
                    and item.material_evidence_fingerprint
                    == record.material_evidence_fingerprint
                ),
                None,
            )
            if prior_material is not None:
                raise ContinuousTradePlanProducerError(
                    "Material producer evidence was reused with a different record identity."
                )
            records.append(record)
            if len(records) > _MAX_RECORDS:
                records = records[-_MAX_RECORDS:]
            self._write_unlocked(tuple(records))
            return record

    def latest_material(
        self, member_id: str, material_fingerprint: str
    ) -> ContinuousProducerRecord | None:
        _require_fingerprint(material_fingerprint, "Material evidence fingerprint")
        return next(
            (
                item
                for item in reversed(self.load())
                if item.member_id == member_id
                and item.material_evidence_fingerprint == material_fingerprint
            ),
            None,
        )

    def _load_unlocked(self) -> tuple[ContinuousProducerRecord, ...]:
        if not self.path.exists():
            return ()
        try:
            raw = self.path.read_bytes()
            if len(raw) > _MAX_STATE_BYTES:
                raise ContinuousTradePlanProducerError(
                    "Continuous producer restart state exceeded its bounded size."
                )
            payload = json.loads(raw)
        except ContinuousTradePlanProducerError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state is unreadable or untrusted."
            ) from exc
        return self.validate_document(payload)

    @staticmethod
    def validate_document(
        payload: object, *, selected_row: Mapping[str, object] | None = None,
    ) -> tuple[ContinuousProducerRecord, ...]:
        """Validate persisted records and their deterministic report projection.

        Shadow may inspect an exact selected row without admitting other rows.
        It still validates every record, and the selected row must equal one
        complete authoritative projection. Full cache reload checks all rows.
        """
        if not isinstance(payload, Mapping) or set(payload) not in (
            {"schemaVersion", "profile", "records"},
            {"schemaVersion", "profile", "records", "candidates"},
        ):
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state schema is invalid."
            )
        if (
            type(payload.get("schemaVersion")) is not int
            or payload.get("schemaVersion") != PRODUCER_SCHEMA_VERSION
            or payload.get("profile") != PRODUCER_PROFILE
            or not isinstance(payload.get("records"), list)
        ):
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state contract is unsupported."
            )
        try:
            records = tuple(
                ContinuousProducerRecord(
                    **{
                        **dict(item),
                        "blockers": tuple(item.get("blockers", ())),
                    }
                )
                for item in payload["records"]
                if isinstance(item, Mapping)
                and isinstance(item.get("blockers", ()), list)
            )
        except (TypeError, ValueError) as exc:
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state contained an invalid record."
            ) from exc
        if len(records) != len(payload["records"]):
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state contained an invalid record."
            )
        identities: set[str] = set()
        for record in records:
            validate_producer_record(record)
            if record.record_id in identities:
                raise ContinuousTradePlanProducerError(
                    "Continuous producer restart state repeated a record identity."
                )
            identities.add(record.record_id)
        expected_rows = [
            row for record in records
            if (row := producer_bound_report_row(record)) is not None
        ]
        if selected_row is None:
            projection_matches = payload.get("candidates", []) == expected_rows
        else:
            projection_matches = (
                isinstance(payload.get("candidates"), list)
                and sum(row == selected_row for row in payload["candidates"]) == 1
                and sum(row == selected_row for row in expected_rows) == 1
            )
        if not projection_matches:
            raise ContinuousTradePlanProducerError(
                "Persisted Producer report rows contradict their authoritative records."
            )
        # Python projection equality alone admits True/1.0 as integer schema 1.
        admitted_rows = payload.get("candidates", [])
        if selected_row is not None:
            admitted_rows = [selected_row, *(
                row for row in admitted_rows if row == selected_row
            )]
        try:
            for row in admitted_rows:
                authoritative_lifecycle_identity_from_report_row(row)
        except LifecyclePositionIdentityError as exc:
            raise ContinuousTradePlanProducerError(
                "Persisted Producer report rows have an invalid authoritative identity."
            ) from exc
        return records

    def _write_unlocked(self, records: tuple[ContinuousProducerRecord, ...]) -> None:
        payload = {
            "schemaVersion": PRODUCER_SCHEMA_VERSION,
            "profile": PRODUCER_PROFILE,
            "records": [asdict(item) for item in records],
            "candidates": [
                row for item in records
                if (row := producer_bound_report_row(item)) is not None
            ],
        }
        content = _canonical_bytes(payload)
        if len(content) > _MAX_STATE_BYTES:
            raise ContinuousTradePlanProducerError(
                "Continuous producer restart state exceeded its bounded size."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class ContinuousHistoryAdmissionCoordinator:
    """Inspect canonical stores and queue missing history while current data loads."""

    def __init__(
        self,
        *,
        minute_store_root: Path,
        daily_store_root: Path,
        backfill: AutomaticCandleBackfillCoordinator,
        policy: ContinuousCompositionPolicy,
    ) -> None:
        self.minute_store_root = Path(minute_store_root)
        self.daily_store_root = Path(daily_store_root)
        self.backfill = backfill
        self.policy = policy

    def admit(
        self,
        *,
        member: HotUniverseMember,
        cutoff: datetime,
        current_evidence_loader: CurrentEvidenceLoader,
        decision_cutoff_provider: Callable[[], datetime] | None = None,
    ) -> HistoryAdmissionResult:
        evaluated = _aware(cutoff)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="MHCurrentEvidence") as pool:
            current_future = pool.submit(
                current_evidence_loader, member.symbol, evaluated
            )
            context, canonical = inspect_historical_context(
                minute_store_root=self.minute_store_root,
                daily_store_root=self.daily_store_root,
                symbol=member.symbol,
                session_date=member.session_date,
                cutoff=evaluated,
                policy=self.policy,
            )
            backfill_evidence: Mapping[str, object] | None = None
            if context.status != HISTORY_READY:
                backfill_evidence = self.backfill.request(
                    member.symbol,
                    reason="CONTINUOUS_NEW_SYMBOL_OR_CONTEXT_NOT_READY",
                )
                status = str(backfill_evidence.get("status", "FAILED"))
                if status in ACTIVE_STATES:
                    context = replace(
                        context,
                        status=HISTORY_BACKFILL_PENDING,
                        backfill_status=status,
                        fingerprint="",
                    )
                    context = _refingerprint_context(context)
                elif status == "FAILED":
                    context = replace(
                        context,
                        status=HISTORY_FAILED,
                        backfill_status=status,
                        blockers=tuple(
                            dict.fromkeys((*context.blockers, "BOUNDED_BACKFILL_FAILED"))
                        ),
                        fingerprint="",
                    )
                    context = _refingerprint_context(context)
            current = current_future.result()
        validate_current_market_evidence(current, expected_symbol=member.symbol)
        if decision_cutoff_provider is None:
            decision_cutoff = max(
                evaluated,
                _parse_timestamp(current.receipt_timestamp),
            )
        else:
            decision_cutoff = _aware(decision_cutoff_provider())
        current_known_at = (("currentMarket", current.receipt_timestamp),)
        if _parse_timestamp(current.receipt_timestamp) > decision_cutoff:
            raise ContinuousEvidenceChronologyError(
                "CURRENT_MARKET_AFTER_DECISION_CUTOFF",
                "Current market evidence arrived after the final decision cutoff.",
                request_cutoff=decision_cutoff.isoformat(),
                evidence_known_at=current_known_at,
            )
        context, canonical = inspect_historical_context(
            minute_store_root=self.minute_store_root,
            daily_store_root=self.daily_store_root,
            symbol=member.symbol,
            session_date=member.session_date,
            cutoff=decision_cutoff,
            policy=self.policy,
        )
        if context.status != HISTORY_READY and backfill_evidence is not None:
            status = str(backfill_evidence.get("status", "FAILED"))
            if status in ACTIVE_STATES:
                context = replace(
                    context,
                    status=HISTORY_BACKFILL_PENDING,
                    backfill_status=status,
                    fingerprint="",
                )
                context = _refingerprint_context(context)
            elif status == "FAILED":
                context = replace(
                    context,
                    status=HISTORY_FAILED,
                    backfill_status=status,
                    blockers=tuple(
                        dict.fromkeys(
                            (*context.blockers, "BOUNDED_BACKFILL_FAILED")
                        )
                    ),
                    fingerprint="",
                )
                context = _refingerprint_context(context)
        evidence_known_at = (
            ("historicalContext", context.evidence_cutoff),
            ("currentMarket", current.receipt_timestamp),
            *(
                (("canonicalMinute", canonical.receipt_timestamp),)
                if canonical is not None
                else ()
            ),
        )
        for label, known_at in evidence_known_at:
            if _parse_timestamp(known_at) > decision_cutoff:
                raise ContinuousEvidenceChronologyError(
                    "EVIDENCE_AFTER_DECISION_CUTOFF",
                    f"{label} became known after the final decision cutoff.",
                    request_cutoff=decision_cutoff.isoformat(),
                    evidence_known_at=evidence_known_at,
                )
        return HistoryAdmissionResult(
            context=context,
            canonical_evidence=canonical,
            current_market_evidence=current,
            backfill_evidence=backfill_evidence,
            current_collection_started_before_backfill_admission=True,
            decision_cutoff=decision_cutoff.isoformat(),
            evidence_known_at=evidence_known_at,
        )


class ContinuousTradePlanProducer:
    """Create one immutable composition/TradePlan packet per material evidence set."""

    def __init__(
        self,
        *,
        store: ContinuousTradePlanProducerStore,
        configuration_fingerprint: str,
        policy: ContinuousCompositionPolicy | None = None,
    ) -> None:
        _require_fingerprint(configuration_fingerprint, "Configuration fingerprint")
        self.store = store
        self.configuration_fingerprint = configuration_fingerprint
        self.policy = policy or ContinuousCompositionPolicy(
            required_recent_minute_bars=1,
        )
        self.producer_fingerprint = _fingerprint(
            {
                "producerVersion": PRODUCER_VERSION,
                "configurationFingerprint": configuration_fingerprint,
                "compositionPolicyFingerprint": self.policy.fingerprint,
                "authority": RESEARCH_ONLY,
                "executionAuthority": EXECUTION_AUTHORITY_NONE,
                "orderCapability": ORDER_CAPABILITY_UNAVAILABLE,
            }
        )

    def evaluate(
        self,
        *,
        universe_state: HotUniverseState,
        member_input: CompositionMemberInput,
        history_context: HistoricalContextEvidence,
        current_market_evidence: CurrentMarketEvidence,
        instrument_admission: InstrumentAdmissionEvidence,
        evidence_cutoff: datetime,
        trigger: str,
        material_evidence_fingerprints: tuple[str, ...] = (),
    ) -> ContinuousProducerEvaluation:
        cutoff = _aware(evidence_cutoff)
        member = next(
            (
                item
                for item in universe_state.members
                if item.member_id == member_input.universe_member_id
            ),
            None,
        )
        if member is None:
            raise ContinuousTradePlanProducerError(
                "Producer input referenced an unknown hot-universe member."
            )
        validate_historical_context(history_context, expected_member=member)
        validate_current_market_evidence(
            current_market_evidence, expected_symbol=member.symbol
        )
        validate_instrument_admission(instrument_admission, expected_symbol=member.symbol)
        if _parse_timestamp(history_context.evidence_cutoff) > cutoff:
            raise ContinuousTradePlanProducerError(
                "Historical context cutoff is later than the producer cutoff."
            )
        if _parse_timestamp(current_market_evidence.receipt_timestamp) > cutoff:
            raise ContinuousTradePlanProducerError(
                "Current market evidence arrived after the producer cutoff."
            )
        if _parse_timestamp(instrument_admission.observed_at) > cutoff:
            raise ContinuousTradePlanProducerError(
                "Instrument admission was observed after the producer cutoff."
            )
        for value in material_evidence_fingerprints:
            _require_fingerprint(value, "Material extension fingerprint")
        if cutoff.astimezone(EASTERN_TZ).date().isoformat() != member.session_date:
            raise ContinuousTradePlanProducerError(
                "Producer cutoff does not match the universe session."
            )
        if history_context.status != HISTORY_READY:
            raise ContinuousTradePlanProducerError(
                "Historical context is not ready for TradePlan composition."
            )
        candidate_origin = _candidate_origin_identity(member)
        material_fingerprint = _fingerprint(
            {
                "candidateOriginIdentity": candidate_origin,
                "memberMaterialIdentity": _member_material_identity(member),
                "historyContentFingerprint": history_context.content_fingerprint,
                "currentMarketEvidenceFingerprint": current_market_evidence.evidence_fingerprint,
                "instrumentAdmissionFingerprint": instrument_admission.evidence_fingerprint,
                "canonicalEvidenceFingerprint": (
                    member_input.canonical_evidence.resolved_fingerprint
                    if member_input.canonical_evidence
                    else ""
                ),
                "rvolEvidenceFingerprint": _nested_fingerprint(
                    member_input.rvol_evidence
                ),
                "lifecycleFingerprint": _nested_fingerprint(member_input.lifecycle),
                "lifecycleTransitionFingerprint": _fingerprint_or_empty(
                    member_input.lifecycle_transition
                ),
                "successorSetupFingerprint": _fingerprint_or_empty(
                    member_input.successor_setup
                ),
                "existingPlanFingerprint": _nested_fingerprint(
                    member_input.existing_plan
                ),
                "materialExtensions": material_evidence_fingerprints,
                "configurationFingerprint": self.configuration_fingerprint,
                "compositionPolicyFingerprint": self.policy.fingerprint,
            }
        )
        admitted_input = member_input
        instrument_blocker = instrument_admission.blocker
        if (
            instrument_blocker
            and instrument_admission.authoritative
            and instrument_admission.instrument_class != UNKNOWN_INSTRUMENT
            and member_input.successor_setup is not None
        ):
            admitted_input = replace(member_input, successor_setup=None)
        existing = self.store.latest_material(member.member_id, material_fingerprint)
        if existing is not None:
            original_cutoff = _parse_timestamp(existing.evidence_cutoff)
            cycle = compose_cycle(
                universe_state=universe_state,
                member_inputs=(admitted_input,),
                started_at=original_cutoff - timedelta(microseconds=1),
                evidence_cutoff=original_cutoff,
                policy=self.policy,
            )
            member_result = next(
                item
                for item in cycle.member_results
                if item.universe_member_id == member.member_id
            )
            if (
                cycle.cycle_id != existing.composition_cycle_id
                or cycle.fingerprint != existing.composition_cycle_fingerprint
                or (
                    member_result.intraday_plan.plan_id
                    if member_result.intraday_plan
                    else ""
                )
                != existing.trade_plan_id
            ):
                raise ContinuousTradePlanProducerError(
                    "Restart recomposition contradicted the preserved producer record."
                )
            return ContinuousProducerEvaluation(
                record=existing,
                cycle=cycle,
                member_result=member_result,
                duplicate=True,
            )

        cycle = compose_cycle(
            universe_state=universe_state,
            member_inputs=(admitted_input,),
            started_at=cutoff - timedelta(microseconds=1),
            evidence_cutoff=cutoff,
            policy=self.policy,
        )
        member_result = next(
            item for item in cycle.member_results if item.universe_member_id == member.member_id
        )
        plan = member_result.intraday_plan
        blockers = tuple(
            dict.fromkeys(
                (
                    *history_context.blockers,
                    *member_result.blocker_reasons,
                    *((instrument_blocker,) if instrument_blocker else ()),
                )
            )
        )
        execution_eligible = bool(
            plan is not None
            and plan.execution_eligible
            and instrument_admission.execution_eligible
            and not blockers
        )
        proposal = member_result.lifecycle_proposal
        lifecycle = admitted_input.lifecycle
        opportunity_id = proposal.opportunity_id if proposal else (
            lifecycle.opportunity_id if lifecycle and lifecycle.current_setup_id else ""
        )
        setup_id = proposal.setup_id if proposal else (
            lifecycle.current_setup_id if lifecycle else ""
        )
        predecessor_setup_id = (
            member_result.lifecycle_proposal.predecessor_setup_id
            if member_result.lifecycle_proposal is not None
            else ""
        )
        payload = {
            "schemaVersion": PRODUCER_SCHEMA_VERSION,
            "profile": PRODUCER_PROFILE,
            "payloadType": "CONTINUOUS_TRADEPLAN_PRODUCER",
            "producerVersion": PRODUCER_VERSION,
            "producerFingerprint": self.producer_fingerprint,
            "trigger": str(trigger).strip().upper(),
            "candidateOriginIdentity": candidate_origin,
            "opportunityId": opportunity_id,
            "setupId": setup_id,
            "tradePlanId": plan.plan_id if plan else "",
            "reportRowContract": 1,
            "lifecycleSnapshot": asdict(lifecycle) if lifecycle else None,
            "historicalContext": asdict(history_context),
            "currentMarketEvidence": asdict(current_market_evidence),
            "instrumentAdmission": asdict(instrument_admission),
            "materialEvidenceFingerprint": material_fingerprint,
            "materialExtensionFingerprints": list(material_evidence_fingerprints),
            "configurationFingerprint": self.configuration_fingerprint,
            "compositionCycle": asdict(cycle),
            "executionEligible": execution_eligible,
            "blockers": list(blockers),
            "authority": RESEARCH_ONLY,
            "executionAuthority": EXECUTION_AUTHORITY_NONE,
            "orderCapability": ORDER_CAPABILITY_UNAVAILABLE,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
        payload_json = _canonical_bytes(payload).decode("ascii")
        payload_fingerprint = hashlib.sha256(payload_json.encode("ascii")).hexdigest()
        core = {
            "member_id": member.member_id,
            "symbol": member.symbol,
            "session_date": member.session_date,
            "candidate_origin_identity": candidate_origin,
            "opportunity_id": opportunity_id,
            "setup_id": setup_id,
            "predecessor_setup_id": predecessor_setup_id,
            "evidence_cutoff": cutoff.isoformat(),
            "historical_context_id": history_context.context_id,
            "historical_context_fingerprint": history_context.fingerprint,
            "current_market_evidence_id": current_market_evidence.evidence_id,
            "current_market_evidence_fingerprint": current_market_evidence.evidence_fingerprint,
            "instrument_admission_id": instrument_admission.evidence_id,
            "instrument_admission_fingerprint": instrument_admission.evidence_fingerprint,
            "material_evidence_fingerprint": material_fingerprint,
            "configuration_fingerprint": self.configuration_fingerprint,
            "composition_policy_fingerprint": self.policy.fingerprint,
            "producer_version": PRODUCER_VERSION,
            "producer_fingerprint": self.producer_fingerprint,
            "composition_cycle_id": cycle.cycle_id,
            "composition_cycle_fingerprint": cycle.fingerprint,
            "trade_plan_id": plan.plan_id if plan else "",
            "trade_plan_fingerprint": plan.fingerprint if plan else "",
            "created_at": plan.created_at if plan else cutoff.isoformat(),
            "entry_expires_at": plan.entry_expires_at if plan else "",
            "lifecycle_state": (
                plan.lifecycle_status if plan else member_result.disposition
            ),
            "execution_eligible": execution_eligible,
            "blockers": blockers,
            "payload_json": payload_json,
            "payload_fingerprint": payload_fingerprint,
            "schema_version": PRODUCER_SCHEMA_VERSION,
            "profile": PRODUCER_PROFILE,
        }
        identity_fingerprint = _fingerprint(
            {
                "memberId": member.member_id,
                "materialEvidenceFingerprint": material_fingerprint,
                "cycleFingerprint": cycle.fingerprint,
                "producerFingerprint": self.producer_fingerprint,
            }
        )
        fingerprint_core = dict(core)
        if not opportunity_id:
            fingerprint_core.pop("opportunity_id")
        record = ContinuousProducerRecord(
            record_id=f"continuous-tradeplan-producer-{identity_fingerprint[:24]}",
            fingerprint=_fingerprint(fingerprint_core),
            **core,
        )
        validate_producer_record(record)
        stored = self.store.append(record)
        return ContinuousProducerEvaluation(
            record=stored,
            cycle=cycle,
            member_result=member_result,
            duplicate=False,
        )


def inspect_historical_context(
    *,
    minute_store_root: Path,
    daily_store_root: Path,
    symbol: str,
    session_date: str,
    cutoff: datetime,
    policy: ContinuousCompositionPolicy,
) -> tuple[HistoricalContextEvidence, CanonicalEvidenceInput | None]:
    """Compose persisted/backfilled canonical evidence without a second store."""

    evaluated = _aware(cutoff)
    completed_cutoff = evaluated - timedelta(
        seconds=policy.minimum_completed_bar_lag_seconds
    )
    finality = load_canonical_minute_finality_as_of(
        cutoff=evaluated,
        store_root=Path(minute_store_root),
        symbols=(symbol,),
    )
    selected_versions = tuple(
        item
        for item in finality.versions
        if _parse_timestamp(item.bar.timestamp) <= completed_cutoff
    )
    all_bars = tuple(item.bar for item in selected_versions)
    current = tuple(
        item
        for item in all_bars
        if item.session_date == session_date
        and datetime.strptime("09:30", "%H:%M").time()
        <= _parse_timestamp(item.timestamp).astimezone(EASTERN_TZ).time()
        < datetime.strptime("16:00", "%H:%M").time()
    )
    daily_store = SchwabDailyCandleStore(Path(daily_store_root))
    daily_payload = daily_store.load_symbol(symbol)
    daily_rows = tuple(
        item
        for item in daily_payload.get("bars", [])
        if isinstance(item, Mapping)
        and str(item.get("sessionDate", "")) < session_date
        and isinstance(item.get("canonicalCandle"), Mapping)
    )
    current_timestamps = {item.timestamp for item in current}
    minute_receipt = max(
        (
            _parse_timestamp(item.first_received_at)
            for item in selected_versions
            if item.bar.timestamp in current_timestamps
        ),
        default=None,
    )
    minute_payload = [asdict(item) for item in all_bars]
    daily_identity_payload = [
        {
            "dailyIdentity": str(item.get("dailyIdentity", "")),
            "canonicalCandle": item.get("canonicalCandle"),
        }
        for item in daily_rows
    ]
    minute_fingerprint = _fingerprint(minute_payload)
    daily_fingerprint = _fingerprint(daily_identity_payload)
    content_fingerprint = _fingerprint(
        {
            "symbol": symbol,
            "minuteEvidenceFingerprint": minute_fingerprint,
            "dailyEvidenceFingerprint": daily_fingerprint,
            "canonicalOutcomeStatesOnly": True,
        }
    )
    sessions = {item.session_date for item in all_bars}
    blockers: list[str] = []
    if not current:
        blockers.append("CANONICAL_CURRENT_SESSION_BARS_MISSING")
    else:
        expected_end = completed_cutoff.replace(second=0, microsecond=0)
        parsed_current = {
            _parse_timestamp(item.timestamp).replace(second=0, microsecond=0)
            for item in current
        }
        expected = tuple(
            expected_end - timedelta(minutes=index)
            for index in range(policy.required_recent_minute_bars - 1, -1, -1)
        )
        if expected_end not in parsed_current:
            blockers.append("CANONICAL_RECENT_WINDOW_NOT_READY")
        elif any(item not in parsed_current for item in expected):
            blockers.append("CANONICAL_CURRENT_WINDOW_GAPPED")
    if len(sessions) < policy.minimum_history_sessions:
        blockers.append("CANONICAL_MINUTE_HISTORY_INSUFFICIENT")
    if policy.required_daily_evidence and not daily_rows:
        blockers.append("CANONICAL_DAILY_HISTORY_MISSING")
    status = HISTORY_READY if not blockers else HISTORY_INSUFFICIENT
    context_core = {
        "symbol": symbol,
        "session_date": session_date,
        "evidence_cutoff": evaluated.isoformat(),
        "earliest_completed_minute": all_bars[0].timestamp if all_bars else "",
        "latest_completed_minute": current[-1].timestamp if current else "",
        "minute_bar_count": len(all_bars),
        "minute_session_count": len(sessions),
        "current_session_bar_count": len(current),
        "daily_bar_count": len(daily_rows),
        "minute_source_identity": "SCHWAB_CANONICAL_RECONCILED_MINUTE_STORE",
        "daily_source_identity": "SCHWAB_CANONICAL_DAILY_STORE",
        "minute_evidence_fingerprint": minute_fingerprint,
        "daily_evidence_fingerprint": daily_fingerprint,
        "content_fingerprint": content_fingerprint,
        "status": status,
        "blockers": tuple(blockers),
        "observed_provisional_version_count": finality.provisional_version_count,
        "admitted_provisional_bar_count": 0,
        "backfill_status": "NOT_REQUESTED",
    }
    context_fingerprint = _fingerprint(
        _historical_context_identity_payload(context_core)
    )
    context = HistoricalContextEvidence(
        context_id=f"continuous-history-{context_fingerprint[:24]}",
        fingerprint=context_fingerprint,
        **context_core,
    )
    canonical: CanonicalEvidenceInput | None = None
    if current:
        receipt = minute_receipt or evaluated
        if receipt > evaluated:
            raise ContinuousTradePlanProducerError(
                "Canonical minute evidence was received after the producer cutoff."
            )
        canonical = CanonicalEvidenceInput(
            evidence_id=context.context_id,
            symbol=symbol,
            session_date=session_date,
            provider_timestamp=current[-1].timestamp,
            receipt_timestamp=receipt.isoformat(),
            bars=current,
            daily_evidence_id=(
                f"continuous-daily:{symbol}:{daily_rows[0]['sessionDate']}:"
                f"{daily_rows[-1]['sessionDate']}"
                if daily_rows
                else ""
            ),
            daily_evidence_fingerprint=daily_fingerprint if daily_rows else "",
            history_depth_sessions=len(sessions),
        )
    validate_historical_context(context)
    return context, canonical


def unavailable_instrument_admission(
    symbol: str, *, observed_at: datetime
) -> InstrumentAdmissionEvidence:
    observed = _aware(observed_at).isoformat()
    core = {
        "symbol": symbol,
        "sourceIdentity": "INSTRUMENT_CLASSIFICATION_UNAVAILABLE",
        "instrumentClass": UNKNOWN_INSTRUMENT,
        "authoritative": False,
        "gap": INSTRUMENT_ADMISSION_GAP,
    }
    fingerprint = _fingerprint(core)
    return InstrumentAdmissionEvidence(
        evidence_id=f"instrument-admission-gap-{fingerprint[:24]}",
        symbol=symbol,
        observed_at=observed,
        source_identity="INSTRUMENT_CLASSIFICATION_UNAVAILABLE",
        instrument_class=UNKNOWN_INSTRUMENT,
        authoritative=False,
        evidence_fingerprint=fingerprint,
    )


def build_current_market_evidence(
    *,
    symbol: str,
    provider_timestamp: str,
    receipt_timestamp: str,
    source_identity: str,
    market_payload: Mapping[str, object],
) -> CurrentMarketEvidence:
    normalized_symbol = str(symbol).strip().upper()
    if str(market_payload.get("symbol", "")).strip().upper() != normalized_symbol:
        raise ContinuousTradePlanProducerError(
            "Current market payload omitted the requested symbol identity."
        )
    market_payload_json = _canonical_bytes(dict(market_payload)).decode("ascii")
    market_payload_fingerprint = hashlib.sha256(
        market_payload_json.encode("ascii")
    ).hexdigest()
    evidence_fingerprint = _fingerprint(
        {
            "symbol": normalized_symbol,
            "providerTimestamp": provider_timestamp,
            "sourceIdentity": source_identity,
            "marketPayloadFingerprint": market_payload_fingerprint,
        }
    )
    evidence = CurrentMarketEvidence(
        evidence_id=f"continuous-current-market-{evidence_fingerprint[:24]}",
        symbol=normalized_symbol,
        provider_timestamp=provider_timestamp,
        receipt_timestamp=receipt_timestamp,
        source_identity=source_identity,
        market_payload_json=market_payload_json,
        market_payload_fingerprint=market_payload_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
    )
    validate_current_market_evidence(evidence, expected_symbol=normalized_symbol)
    return evidence


def validate_current_market_evidence(
    evidence: CurrentMarketEvidence, *, expected_symbol: str
) -> None:
    if evidence.symbol != expected_symbol or not evidence.evidence_id:
        raise ContinuousTradePlanProducerError(
            "Current market evidence identity mismatched the producer symbol."
        )
    _parse_timestamp(evidence.provider_timestamp)
    receipt = _parse_timestamp(evidence.receipt_timestamp)
    provider = _parse_timestamp(evidence.provider_timestamp)
    if provider > receipt:
        raise ContinuousTradePlanProducerError(
            "Current market evidence receipt predates its provider timestamp."
        )
    if not evidence.source_identity:
        raise ContinuousTradePlanProducerError(
            "Current market evidence source identity is required."
        )
    try:
        payload = json.loads(evidence.market_payload_json)
    except json.JSONDecodeError as exc:
        raise ContinuousTradePlanProducerError(
            "Current market evidence payload is malformed."
        ) from exc
    if not isinstance(payload, Mapping) or str(payload.get("symbol", "")) != expected_symbol:
        raise ContinuousTradePlanProducerError(
            "Current market evidence payload identity mismatched."
        )
    if (
        hashlib.sha256(evidence.market_payload_json.encode("ascii")).hexdigest()
        != evidence.market_payload_fingerprint
    ):
        raise ContinuousTradePlanProducerError(
            "Current market evidence payload fingerprint did not verify."
        )
    _require_fingerprint(
        evidence.market_payload_fingerprint, "Current market payload fingerprint"
    )
    _require_fingerprint(evidence.evidence_fingerprint, "Current market evidence fingerprint")
    expected_fingerprint = _fingerprint(
        {
            "symbol": evidence.symbol,
            "providerTimestamp": evidence.provider_timestamp,
            "sourceIdentity": evidence.source_identity,
            "marketPayloadFingerprint": evidence.market_payload_fingerprint,
        }
    )
    if (
        evidence.evidence_fingerprint != expected_fingerprint
        or evidence.evidence_id
        != f"continuous-current-market-{expected_fingerprint[:24]}"
    ):
        raise ContinuousTradePlanProducerError(
            "Current market evidence fingerprint or identity did not verify."
        )


def validate_instrument_admission(
    evidence: InstrumentAdmissionEvidence, *, expected_symbol: str
) -> None:
    if evidence.symbol != expected_symbol or not evidence.evidence_id:
        raise ContinuousTradePlanProducerError(
            "Instrument admission identity mismatched the producer symbol."
        )
    _parse_timestamp(evidence.observed_at)
    if evidence.instrument_class not in INSTRUMENT_CLASSES:
        raise ContinuousTradePlanProducerError(
            "Instrument admission class is unsupported."
        )
    if evidence.authoritative and evidence.source_identity == "INSTRUMENT_CLASSIFICATION_UNAVAILABLE":
        raise ContinuousTradePlanProducerError(
            "Unavailable instrument evidence cannot claim authority."
        )
    _require_fingerprint(evidence.evidence_fingerprint, "Instrument admission fingerprint")


def validate_historical_context(
    context: HistoricalContextEvidence, *, expected_member: HotUniverseMember | None = None
) -> None:
    if (
        context.status not in HISTORY_STATES
        or context.admitted_provisional_bar_count != 0
    ):
        raise ContinuousTradePlanProducerError(
            "Historical context state or provisional-bar boundary is invalid."
        )
    if expected_member is not None and (
        context.symbol != expected_member.symbol
        or context.session_date != expected_member.session_date
    ):
        raise ContinuousTradePlanProducerError(
            "Historical context identity mismatched the universe member."
        )
    _parse_timestamp(context.evidence_cutoff)
    for value in (
        context.minute_bar_count,
        context.minute_session_count,
        context.current_session_bar_count,
        context.daily_bar_count,
        context.observed_provisional_version_count,
        context.admitted_provisional_bar_count,
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContinuousTradePlanProducerError(
                "Historical context counts must be nonnegative integers."
            )
    for value, label in (
        (context.minute_evidence_fingerprint, "Minute context fingerprint"),
        (context.daily_evidence_fingerprint, "Daily context fingerprint"),
        (context.content_fingerprint, "History content fingerprint"),
        (context.fingerprint, "Historical context fingerprint"),
    ):
        _require_fingerprint(value, label)
    expected = _fingerprint(_historical_context_identity_payload(asdict(context)))
    if context.fingerprint != expected or context.context_id != f"continuous-history-{expected[:24]}":
        raise ContinuousTradePlanProducerError(
            "Historical context fingerprint or identity did not verify."
        )


def validate_producer_record(record: ContinuousProducerRecord) -> None:
    if (
        type(record.schema_version) is not int
        or record.schema_version != PRODUCER_SCHEMA_VERSION
        or record.profile != PRODUCER_PROFILE
        or record.producer_version != PRODUCER_VERSION
        or record.symbol.strip().upper() != record.symbol
    ):
        raise ContinuousTradePlanProducerError(
            "Continuous producer record contract is unsupported."
        )
    for value, label in (
        (record.candidate_origin_identity, "Candidate origin fingerprint"),
        (record.historical_context_fingerprint, "Historical context fingerprint"),
        (record.current_market_evidence_fingerprint, "Current evidence fingerprint"),
        (record.instrument_admission_fingerprint, "Instrument admission fingerprint"),
        (record.material_evidence_fingerprint, "Material evidence fingerprint"),
        (record.configuration_fingerprint, "Configuration fingerprint"),
        (record.composition_policy_fingerprint, "Composition policy fingerprint"),
        (record.producer_fingerprint, "Producer fingerprint"),
        (record.composition_cycle_fingerprint, "Composition cycle fingerprint"),
        (record.payload_fingerprint, "Producer payload fingerprint"),
        (record.fingerprint, "Producer record fingerprint"),
    ):
        _require_fingerprint(value, label)
    if record.trade_plan_id:
        _require_fingerprint(record.trade_plan_fingerprint, "TradePlan fingerprint")
    elif record.trade_plan_fingerprint:
        raise ContinuousTradePlanProducerError(
            "Producer record has a TradePlan fingerprint without an identity."
        )
    if hashlib.sha256(record.payload_json.encode("ascii")).hexdigest() != record.payload_fingerprint:
        raise ContinuousTradePlanProducerError(
            "Continuous producer payload fingerprint did not verify."
        )
    try:
        payload = json.loads(record.payload_json)
    except json.JSONDecodeError as exc:
        raise ContinuousTradePlanProducerError(
            "Continuous producer payload is malformed."
        ) from exc
    historical = _is_precontract_producer_record(record, payload)
    lifecycle_ids = (record.opportunity_id, record.setup_id)
    if not historical and any(lifecycle_ids) and not all(lifecycle_ids):
        raise ContinuousTradePlanProducerError(
            "Producer lifecycle opportunity/setup identity is incomplete."
        )
    if record.opportunity_id:
        _require_fingerprint(record.opportunity_id, "Lifecycle opportunity identity")
        _require_fingerprint(record.setup_id, "Lifecycle setup identity")
    if not historical and (
        not isinstance(payload, Mapping)
        or set(_MODERN_PRODUCER_FIELDS) - set(payload)
        or type(payload.get("reportRowContract")) is not int
        or payload.get("reportRowContract") != 1
    ):
        raise ContinuousTradePlanProducerError("Modern Producer lineage is incomplete.")
    explicit_identity_fields = {
        "opportunityId",
        "setupId",
        "tradePlanId",
    }.intersection(payload if isinstance(payload, Mapping) else {})
    if isinstance(payload, Mapping) and "reportRowContract" in payload and (
        type(payload["reportRowContract"]) is not int or payload["reportRowContract"] != 1
    ):
        raise ContinuousTradePlanProducerError("Producer report row contract is unsupported.")
    if explicit_identity_fields and explicit_identity_fields != {
        "opportunityId",
        "setupId",
        "tradePlanId",
    }:
        raise ContinuousTradePlanProducerError(
            "Continuous producer payload lifecycle identity is incomplete."
        )
    if explicit_identity_fields and record.trade_plan_id and not all(lifecycle_ids):
        raise ContinuousTradePlanProducerError(
            "Producer TradePlan is missing authoritative lifecycle provenance."
        )
    if (
        not isinstance(payload, Mapping)
        or type(payload.get("schemaVersion")) is not int
        or payload.get("schemaVersion") != record.schema_version
        or payload.get("profile") != record.profile
        or payload.get("producerVersion") != record.producer_version
        or payload.get("payloadType") != "CONTINUOUS_TRADEPLAN_PRODUCER"
        or payload.get("producerFingerprint") != record.producer_fingerprint
        or payload.get("materialEvidenceFingerprint")
        != record.material_evidence_fingerprint
        or payload.get("configurationFingerprint")
        != record.configuration_fingerprint
        or payload.get("executionEligible") != record.execution_eligible
        or tuple(payload.get("blockers", ())) != record.blockers
        or payload.get("authority") != RESEARCH_ONLY
        or payload.get("executionAuthority") != EXECUTION_AUTHORITY_NONE
        or payload.get("orderCapability") != ORDER_CAPABILITY_UNAVAILABLE
        or payload.get("accountValuesRequested") is not False
        or payload.get("positionsRequested") is not False
        or payload.get("ordersRequested") is not False
        or (
            bool(record.opportunity_id)
            and (
                payload.get("opportunityId") != record.opportunity_id
                or payload.get("setupId") != record.setup_id
                or payload.get("tradePlanId") != record.trade_plan_id
            )
        )
    ):
        raise ContinuousTradePlanProducerError(
            "Continuous producer payload identity is contradictory."
        )
    history = payload.get("historicalContext")
    current = payload.get("currentMarketEvidence")
    instrument = payload.get("instrumentAdmission")
    cycle = payload.get("compositionCycle")
    if (
        not isinstance(history, Mapping)
        or history.get("context_id") != record.historical_context_id
        or history.get("fingerprint") != record.historical_context_fingerprint
        or not isinstance(current, Mapping)
        or current.get("evidence_id") != record.current_market_evidence_id
        or current.get("evidence_fingerprint")
        != record.current_market_evidence_fingerprint
        or not isinstance(instrument, Mapping)
        or instrument.get("evidence_id") != record.instrument_admission_id
        or instrument.get("evidence_fingerprint")
        != record.instrument_admission_fingerprint
        or not isinstance(cycle, Mapping)
        or cycle.get("cycle_id") != record.composition_cycle_id
        or cycle.get("fingerprint") != record.composition_cycle_fingerprint
    ):
        raise ContinuousTradePlanProducerError(
            "Continuous producer embedded evidence identity is contradictory."
        )
    if explicit_identity_fields:
        member_results = cycle.get("member_results")
        matching_results = (
            [
                item
                for item in member_results
                if isinstance(item, Mapping)
                and item.get("universe_member_id") == record.member_id
            ]
            if isinstance(member_results, list)
            else []
        )
        if len(matching_results) != 1:
            raise ContinuousTradePlanProducerError(
                "Continuous producer lifecycle result identity is unavailable."
            )
        member_result = matching_results[0]
        proposal = member_result.get("lifecycle_proposal")
        if record.opportunity_id:
            if isinstance(proposal, Mapping):
                if (
                    proposal.get("opportunity_id") != record.opportunity_id
                    or proposal.get("setup_id") != record.setup_id
                ):
                    raise ContinuousTradePlanProducerError(
                        "Producer lifecycle provenance contradicts its composition result."
                    )
            else:
                snapshot = payload.get("lifecycleSnapshot")
                if not isinstance(snapshot, Mapping) or (
                    snapshot.get("symbol") != record.symbol
                    or snapshot.get("session_date") != record.session_date
                    or snapshot.get("opportunity_id") != record.opportunity_id
                    or snapshot.get("current_setup_id") != record.setup_id
                    or not snapshot.get("latest_event_id")
                    or expected_opportunity_id(
                        record.symbol, record.session_date,
                        str(snapshot.get("originating_evidence_family", "")),
                    ) != record.opportunity_id
                    or expected_setup_id(
                        record.opportunity_id,
                        str(snapshot.get("current_setup_family", "")),
                        snapshot.get("current_setup_sequence", 0),
                    ) != record.setup_id
                    or _parse_timestamp(str(snapshot.get("updated_at", "")))
                    > _parse_timestamp(record.evidence_cutoff)
                ):
                    raise ContinuousTradePlanProducerError(
                        "Producer ongoing lifecycle provenance is unavailable or contradictory."
                    )
        plan = member_result.get("intraday_plan")
        if record.trade_plan_id and (
            not isinstance(plan, Mapping)
            or plan.get("plan_id") != record.trade_plan_id
        ):
            raise ContinuousTradePlanProducerError(
                "Producer TradePlan identity contradicts its composition result."
            )
    core = asdict(record)
    core.pop("record_id")
    core.pop("fingerprint")
    if not record.opportunity_id:
        # Pre-contract records remain readable, but cannot emit a proven binding.
        core.pop("opportunity_id")
    if record.fingerprint != _fingerprint(core):
        raise ContinuousTradePlanProducerError(
            "Continuous producer record fingerprint did not verify."
        )
    identity = _fingerprint(
        {
            "memberId": record.member_id,
            "materialEvidenceFingerprint": record.material_evidence_fingerprint,
            "cycleFingerprint": record.composition_cycle_fingerprint,
            "producerFingerprint": record.producer_fingerprint,
        }
    )
    if record.record_id != f"continuous-tradeplan-producer-{identity[:24]}":
        raise ContinuousTradePlanProducerError(
            "Continuous producer record identity did not verify."
        )
    if record.execution_eligible and (not record.trade_plan_id or record.blockers):
        raise ContinuousTradePlanProducerError(
            "Execution-eligible producer record is incomplete or blocked."
        )


_MODERN_PRODUCER_FIELDS = frozenset({
    "opportunityId", "setupId", "tradePlanId", "reportRowContract", "lifecycleSnapshot",
})
_PRECONTRACT_PAYLOAD_FIELDS = frozenset({
    "schemaVersion", "profile", "payloadType", "producerVersion", "producerFingerprint",
    "trigger", "candidateOriginIdentity", "historicalContext", "currentMarketEvidence",
    "instrumentAdmission", "materialEvidenceFingerprint", "materialExtensionFingerprints",
    "configurationFingerprint", "compositionCycle", "executionEligible", "blockers",
    "authority", "executionAuthority", "orderCapability", "accountValuesRequested",
    "positionsRequested", "ordersRequested",
})


def _is_precontract_producer_record(record: ContinuousProducerRecord, payload: object) -> bool:
    # Historical privilege requires the exact old payload contract AND the old
    # record hash committing to those bytes. Deleting modern fields alone fails.
    if not isinstance(payload, Mapping) or set(payload) != _PRECONTRACT_PAYLOAD_FIELDS:
        return False
    core = asdict(record)
    for field in ("record_id", "fingerprint", "opportunity_id"):
        core.pop(field)
    return (
        record.opportunity_id == ""
        and type(payload.get("schemaVersion")) is int
        and payload.get("schemaVersion") == PRODUCER_SCHEMA_VERSION
        and payload.get("profile") == PRODUCER_PROFILE
        and payload.get("producerVersion") == PRODUCER_VERSION
        and record.fingerprint == _fingerprint(core)
    )


def producer_bound_report_row(record: ContinuousProducerRecord) -> dict[str, object] | None:
    """Serialize issued levels and provenance, never manufacture execution readiness.

    The row is a deterministic projection, outside the record fingerprint to
    avoid a self-referential binding. Store load verifies the entire projection.
    Old records are not retrospectively upgraded to the new report contract.
    """

    validate_producer_record(record)
    payload = json.loads(record.payload_json)
    if payload.get("reportRowContract") != 1 or not record.trade_plan_id:
        return None
    results = payload["compositionCycle"]["member_results"]
    result = next(item for item in results if item["universe_member_id"] == record.member_id)
    plan = result["intraday_plan"]
    targets = plan["target_prices"]
    row = {
        "symbol": record.symbol,
        "opportunity_id": record.opportunity_id,
        "setup_id": record.setup_id,
        "trade_plan_id": record.trade_plan_id,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY_NONE,
        "orderCapability": ORDER_CAPABILITY_UNAVAILABLE,
        "trade_plan": {
            "bullish_entry": plan["planned_entry"],
            "bullish_stop": plan["stop_price"],
            "bullish_target_1": targets[0] if targets else None,
            "bullish_target_2": targets[1] if len(targets) > 1 else None,
            "risk_reward_ratio": None,
            "estimated_shares_for_500": None,
            "estimated_dollar_risk": None,
            "estimated_target_1_reward": None,
            "confidence": "UNAVAILABLE",
            "tradeability": RESEARCH_ONLY,
            "readiness": "PLANNING_SCAFFOLD",
            "blocking_reasons": list(dict.fromkeys((*record.blockers, "RESEARCH_ONLY"))),
            "warnings": [],
            "intraday_evidence": plan,
        },
    }
    return bind_report_row_to_producer_identity(row, record)


def _refingerprint_context(context: HistoricalContextEvidence) -> HistoricalContextEvidence:
    fingerprint = _fingerprint(
        _historical_context_identity_payload(asdict(context))
    )
    return replace(
        context,
        context_id=f"continuous-history-{fingerprint[:24]}",
        fingerprint=fingerprint,
    )


def _historical_context_identity_payload(
    context: Mapping[str, object],
) -> dict[str, object]:
    """Return only decision-authoritative historical-context identity inputs."""

    return {
        key: value
        for key, value in context.items()
        if key
        not in {
            "context_id",
            "fingerprint",
            "observed_provisional_version_count",
        }
    }


def _nested_fingerprint(value: object | None) -> str:
    if value is None:
        return ""
    candidate = getattr(value, "fingerprint", "")
    if isinstance(candidate, str) and _SHA256.fullmatch(candidate):
        return candidate
    return _fingerprint(asdict(value))


def _candidate_origin_identity(member: HotUniverseMember) -> str:
    return _fingerprint(
        {
            "memberId": member.member_id,
            "membershipGeneration": member.membership_generation,
            "firstObservedAt": member.first_observed_at,
            "firstDiscoverySnapshotId": member.first_discovery_snapshot_id,
            "firstCandidateIdentity": member.first_candidate_identity,
            "admissionReason": member.admission_reason,
        }
    )


def _member_material_identity(member: HotUniverseMember) -> str:
    return _fingerprint(
        {
            "latestCandidateIdentity": member.latest_candidate_identity,
            "currentTier": member.current_tier,
            "currentState": member.current_state,
            "consecutiveAbsentObservations": member.consecutive_absent_observations,
            "consecutiveRejectedObservations": member.consecutive_rejected_observations,
            "activeSetupIds": member.active_setup_ids,
            "terminalSetupCount": member.terminal_setup_count,
            "protectedReason": member.protected_reason,
            "priorityInputs": member.priority_inputs,
            "capacityDisposition": member.capacity_disposition,
            "providerBoundSince": member.provider_bound_since,
        }
    )


def _fingerprint_or_empty(value: object | None) -> str:
    return "" if value is None else _nested_fingerprint(value)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_fingerprint(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContinuousTradePlanProducerError(f"{label} must be SHA-256.")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuousTradePlanProducerError("Producer timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousTradePlanProducerError("Producer timestamp must include an offset.")
    return parsed


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContinuousTradePlanProducerError(
            "Producer evaluation requires a timezone-aware timestamp."
        )
    return value


__all__ = [
    "COMMON_STOCK",
    "ETN",
    "EXECUTION_AUTHORITY_NONE",
    "HISTORY_BACKFILL_PENDING",
    "HISTORY_FAILED",
    "HISTORY_INSUFFICIENT",
    "HISTORY_READY",
    "INSTRUMENT_ADMISSION_GAP",
    "INVERSE_ETP",
    "LEVERAGED_ETP",
    "ORDINARY_ETF",
    "ORDER_CAPABILITY_UNAVAILABLE",
    "PRODUCER_PROFILE",
    "PRODUCER_VERSION",
    "RESEARCH_ONLY",
    "UNKNOWN_INSTRUMENT",
    "ContinuousEvidenceChronologyError",
    "ContinuousHistoryAdmissionCoordinator",
    "ContinuousProducerEvaluation",
    "ContinuousProducerRecord",
    "ContinuousTradePlanProducer",
    "ContinuousTradePlanProducerError",
    "ContinuousTradePlanProducerStore",
    "CurrentMarketEvidence",
    "HistoricalContextEvidence",
    "HistoryAdmissionResult",
    "InstrumentAdmissionEvidence",
    "build_current_market_evidence",
    "inspect_historical_context",
    "unavailable_instrument_admission",
    "validate_current_market_evidence",
    "validate_historical_context",
    "validate_instrument_admission",
    "validate_producer_record",
]
