"""Natural lifecycle and setup ownership for the Continuous research runtime.

This adapter connects completed canonical bars to the existing sequential-
breakout detector, candidate lifecycle ledger, and Continuous composition
contracts. It derives no provider data and owns no execution capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_CONFIRMED as LIFECYCLE_BREAKOUT_CONFIRMED,
    BREAKOUT_FORMING,
    CANDIDATE_STATES,
    DISCOVERED,
    ENTRY_MISSED as LIFECYCLE_ENTRY_MISSED,
    EXHAUSTION_RISK as LIFECYCLE_EXHAUSTION_RISK,
    FAILED_BREAKOUT as LIFECYCLE_FAILED_BREAKOUT,
    IMPULSE_DETECTED as LIFECYCLE_IMPULSE_DETECTED,
    INVALIDATED as LIFECYCLE_INVALIDATED,
    LEGAL_TRANSITIONS,
    SETUP_STATE_CHANGED,
    WATCHING,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleSnapshot,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_composition import (
    CompositionMemberInput,
    LifecycleTransitionInput,
    SuccessorSetupEvidence,
)
from momentum_hunter.canonical_candle_evidence import (
    CanonicalMinuteFinalitySnapshot,
    load_canonical_minute_finality_as_of,
)
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousProducerEvaluation,
    ContinuousProducerRecord,
    ContinuousTradePlanProducerStore,
)
from momentum_hunter.hot_universe import HotUniverseMember, HotUniverseState, TRACKED
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
    IntradayPlanEvidence,
)
from momentum_hunter.path_transaction import PathTransactionLease
from momentum_hunter.schwab_candle_contract import EASTERN_TZ
from momentum_hunter.sequential_breakout_research import (
    BREAKOUT_CONFIRMED,
    DATA_UNAVAILABLE,
    ENTRY_MISSED,
    EXHAUSTION_RISK,
    FAILED_BREAKOUT,
    IMPULSE_DETECTED,
    HISTORICAL_REPLAY,
    PROSPECTIVE,
    PULLBACK_FORMING,
    RECLAIM_CONFIRMED,
    SequentialBreakoutEvent,
    SequentialBreakoutPolicy,
    SequentialBreakoutStore,
    detect_sequential_breakout_events,
    observation_from_canonical_bar,
)


NATURAL_SETUP_PROFILE = "continuous-natural-setup-runtime-v1"
ORIGINATING_EVIDENCE_FAMILY = "CONTINUOUS_HOT_UNIVERSE"
SOURCE_IDENTITY = "CONTINUOUS_SEQUENTIAL_COMPLETED_CANONICAL_BAR"
LEVEL_KIND = "SEQUENTIAL_TRIGGER_AND_PRIOR_COMPLETED_BAR_RANGE"
UNKNOWN_EVENT = "NO_NATURAL_SETUP_TRANSITION"
MAX_MATERIAL_EXTENSIONS = 1_024
_COMPOSITION_JOURNAL = ".continuous-natural-composition-journal.json"
_COMPOSITION_TRANSACTION_PREFIX = ".continuous-natural-composition-transaction-"


class ContinuousNaturalSetupError(ValueError):
    """Raised when natural runtime chronology is incomplete or contradictory."""


@dataclass(frozen=True)
class CompletedBarMaterialEvent:
    event_id: str
    symbol: str
    provider_timestamp: str
    receipt_timestamp: str
    source_fingerprint: str
    bar_fingerprint: str
    profile: str = NATURAL_SETUP_PROFILE


@dataclass(frozen=True)
class NaturalCompositionStep:
    member_input: CompositionMemberInput
    material_fingerprints: tuple[str, ...]
    event_id: str
    event_type: str
    event_fingerprint: str
    direct_transition_count: int = 0
    confirm_breakout_after_commit: bool = False


class ContinuousNaturalSetupCoordinator:
    """Own natural research lifecycle/setup state under one explicit runtime root."""

    def __init__(
        self,
        *,
        root: Path,
        minute_store_root: Path,
        producer_store: ContinuousTradePlanProducerStore,
        runtime_started_at: datetime,
    ) -> None:
        self.root = Path(root)
        self.minute_store_root = Path(minute_store_root)
        self.producer_store = producer_store
        self.runtime_started_at = _aware(runtime_started_at, "Runtime start")
        self.lifecycle_policy = CandidateLifecyclePolicy(
            policy_version="continuous-natural-lifecycle-v1",
            cooldown_seconds=300,
            hysteresis_profile="SEQUENTIAL_BREAKOUT_POLICY_V1",
            minimum_delta_profile="COMPLETED_CANONICAL_BAR_ONLY",
            quote_only_events_create_cycles=False,
        )
        self.lifecycle = CandidateLifecycleCoordinator(
            CandidateLifecycleStore(self.root / "candidate-lifecycle.json"),
            policy=self.lifecycle_policy,
        )
        self.breakout_policy = SequentialBreakoutPolicy()
        self.breakouts = SequentialBreakoutStore(
            self.root / "sequential-breakout.json",
            policy=self.breakout_policy,
        )
        self._recover_interrupted_composition()

    def preview(self) -> "NaturalCompositionPreview":
        """Stage all natural/Producer mutations outside authoritative state."""

        return NaturalCompositionPreview(self)

    def completed_bar_events(
        self,
        *,
        universe_state: HotUniverseState | None,
        cutoff: datetime,
    ) -> tuple[CompletedBarMaterialEvent, ...]:
        """Return completed bars not yet bound into a producer record."""

        if universe_state is None:
            return ()
        known = self._processed_material_fingerprints()
        events: list[CompletedBarMaterialEvent] = []
        for member in universe_state.members:
            if member.current_state != TRACKED:
                continue
            observations = self._observations(member, cutoff=cutoff)
            for observation in observations:
                if observation.observation_mode != PROSPECTIVE:
                    continue
                if observation.source_evidence_fingerprint in known:
                    continue
                identity_payload = {
                    "symbol": member.symbol,
                    "providerTimestamp": observation.provider_timestamp,
                    "barFingerprint": observation.source_evidence_fingerprint,
                    "sourceEvidenceFingerprint": observation.source_evidence_fingerprint,
                }
                fingerprint = _fingerprint(
                    "continuous-completed-bar-material-v2", identity_payload
                )
                events.append(
                    CompletedBarMaterialEvent(
                        event_id=f"continuous-completed-bar-{fingerprint[:24]}",
                        symbol=member.symbol,
                        provider_timestamp=observation.provider_timestamp,
                        receipt_timestamp=observation.receipt_timestamp,
                        source_fingerprint=fingerprint,
                        bar_fingerprint=observation.source_evidence_fingerprint,
                    )
                )
        return tuple(
            sorted(events, key=lambda item: (item.provider_timestamp, item.symbol))
        )

    def ensure_lifecycle(
        self,
        *,
        member: HotUniverseMember,
        cutoff: datetime,
        readiness_fingerprint: str,
    ) -> CandidateLifecycleSnapshot:
        """Discover and promote a member to WATCHING without caller injection."""

        observed = _parse_timestamp(member.first_observed_at)
        if observed > cutoff:
            raise ContinuousNaturalSetupError(
                "Hot-universe membership became known after the composition cutoff."
            )
        evidence = _sha_or_fingerprint(member.first_candidate_identity)
        result = self.lifecycle.discover(
            symbol=member.symbol,
            session_date=member.session_date,
            originating_evidence_family=ORIGINATING_EVIDENCE_FAMILY,
            evidence_fingerprint=evidence,
            source_identity=(
                f"CONTINUOUS_HOT_UNIVERSE:{member.first_discovery_snapshot_id}"
            ),
            occurred_at=observed,
            provider_timestamp=observed,
            receipt_timestamp=observed,
            reason="NATURAL_HOT_UNIVERSE_ADMISSION",
        )
        snapshot = result.snapshot
        if snapshot is None:
            raise ContinuousNaturalSetupError("Natural lifecycle discovery returned no state.")
        if snapshot.current_state == DISCOVERED:
            watched = self.lifecycle.transition(
                opportunity_id=snapshot.opportunity_id,
                next_state=WATCHING,
                evidence_fingerprint=readiness_fingerprint,
                source_identity="CONTINUOUS_CANONICAL_READINESS",
                occurred_at=cutoff,
                provider_timestamp=cutoff,
                receipt_timestamp=cutoff,
                reason="CANONICAL_HISTORY_AND_CURRENT_EVIDENCE_READY",
                material_delta_kind=SETUP_STATE_CHANGED,
            )
            snapshot = watched.snapshot
        if snapshot is None:
            raise ContinuousNaturalSetupError("Natural lifecycle promotion returned no state.")
        return snapshot

    def next_step(
        self,
        *,
        member: HotUniverseMember,
        base_input: CompositionMemberInput,
        cutoff: datetime,
        readiness_fingerprint: str,
        request_material_fingerprint: str,
    ) -> NaturalCompositionStep:
        """Build the next unrecorded natural step, or one truthful unchanged step."""

        lifecycle = self.ensure_lifecycle(
            member=member,
            cutoff=cutoff,
            readiness_fingerprint=readiness_fingerprint,
        )
        observations = self._observations(member, cutoff=cutoff)
        if not observations:
            return self._unchanged_step(
                base_input,
                lifecycle,
                request_material_fingerprint,
                event_type=DATA_UNAVAILABLE,
            )
        prospective_floor = self._prospective_floor(member)
        detected = detect_sequential_breakout_events(
            observations,
            originating_evidence_family=ORIGINATING_EVIDENCE_FAMILY,
            policy=self.breakout_policy,
            minimum_event_timestamp=prospective_floor,
        )
        self.breakouts.append(detected)
        processed = self._processed_event_fingerprints(member.member_id)
        prior_records = self._member_records(member.member_id)
        pending = [
            event
            for event in detected
            if event.fingerprint not in processed
            and _parse_timestamp(event.provider_timestamp) >= prospective_floor
        ]
        if pending:
            return self._step_for_event(
                event=pending[0],
                member=member,
                base_input=base_input,
                lifecycle=lifecycle,
                cutoff=cutoff,
                request_material_fingerprint=request_material_fingerprint,
            )
        unprocessed_bars = tuple(
            item.source_evidence_fingerprint
            for item in observations
            if item.observation_mode == PROSPECTIVE
            if item.source_evidence_fingerprint
            not in self._processed_material_fingerprints(member.member_id)
        )
        if not unprocessed_bars and prior_records:
            latest_payload = json.loads(prior_records[-1].payload_json)
            prior_extensions = latest_payload.get(
                "materialExtensionFingerprints", []
            )
            if isinstance(prior_extensions, list):
                unprocessed_bars = tuple(str(item) for item in prior_extensions)
        return self._unchanged_step(
            base_input,
            lifecycle,
            request_material_fingerprint,
            material_fingerprints=unprocessed_bars,
        )

    def commit(
        self,
        *,
        step: NaturalCompositionStep,
        evaluation: ContinuousProducerEvaluation,
    ) -> int:
        """Commit an accepted composition proposal to the lifecycle ledger."""

        member_result = evaluation.member_result
        if member_result is None:
            raise ContinuousNaturalSetupError("Natural producer omitted its member result.")
        proposal = member_result.lifecycle_proposal
        transitions = step.direct_transition_count
        if proposal is not None:
            self._apply_proposal(proposal)
            transitions += 1
        if step.confirm_breakout_after_commit and proposal is not None:
            current = self.lifecycle.snapshot(proposal.opportunity_id)
            if current is not None and current.current_state == BREAKOUT_FORMING:
                self.lifecycle.transition(
                    opportunity_id=current.opportunity_id,
                    next_state=LIFECYCLE_BREAKOUT_CONFIRMED,
                    evidence_fingerprint=_transition_evidence_fingerprint(
                        step.event_fingerprint,
                        LIFECYCLE_BREAKOUT_CONFIRMED,
                    ),
                    source_identity=SOURCE_IDENTITY,
                    occurred_at=_parse_timestamp(proposal.receipt_timestamp),
                    provider_timestamp=_parse_timestamp(proposal.provider_timestamp),
                    receipt_timestamp=_parse_timestamp(proposal.receipt_timestamp),
                    reason="COMPLETED_CANONICAL_BAR_CONFIRMED_BREAKOUT",
                    material_delta_kind=SETUP_STATE_CHANGED,
                    setup_family=current.current_setup_family,
                )
                transitions += 1
        return transitions

    def latest_plan(self, member_id: str, setup_id: str = "") -> IntradayPlanEvidence | None:
        for record in reversed(self._member_records(member_id)):
            if setup_id and record.setup_id != setup_id:
                continue
            payload = json.loads(record.payload_json)
            cycle = payload.get("compositionCycle")
            if not isinstance(cycle, Mapping):
                continue
            results = cycle.get("member_results")
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, Mapping):
                    continue
                raw = result.get("intraday_plan")
                if isinstance(raw, Mapping):
                    return _intraday_plan_from_wire(raw)
        return None

    def _step_for_event(
        self,
        *,
        event: SequentialBreakoutEvent,
        member: HotUniverseMember,
        base_input: CompositionMemberInput,
        lifecycle: CandidateLifecycleSnapshot,
        cutoff: datetime,
        request_material_fingerprint: str,
    ) -> NaturalCompositionStep:
        if _parse_timestamp(event.receipt_timestamp) > cutoff:
            raise ContinuousNaturalSetupError(
                "Sequential setup evidence became known after the decision cutoff."
            )
        material = tuple(
            dict.fromkeys(
                (
                    request_material_fingerprint,
                    event.source_evidence_fingerprint,
                    self._event_observation_fingerprint(event, member, cutoff),
                    event.fingerprint,
                )
            )
        )
        existing = self.latest_plan(member.member_id, lifecycle.current_setup_id)
        direct = 0
        successor: SuccessorSetupEvidence | None = None
        transition: LifecycleTransitionInput | None = None
        confirm = False

        if event.event_type == IMPULSE_DETECTED:
            lifecycle, direct = self._apply_direct_event(
                event, lifecycle, LIFECYCLE_IMPULSE_DETECTED
            )
        elif event.event_type == BREAKOUT_CONFIRMED:
            if event.setup_family == OPENING_BREAKOUT:
                lifecycle, direct = self._apply_direct_event(
                    event,
                    lifecycle,
                    BREAKOUT_FORMING,
                    setup_family=OPENING_BREAKOUT,
                    create_new_setup=not lifecycle.current_setup_id,
                )
                if LIFECYCLE_BREAKOUT_CONFIRMED in LEGAL_TRANSITIONS.get(
                    lifecycle.current_state, frozenset()
                ):
                    lifecycle, extra = self._apply_direct_event(
                        event,
                        lifecycle,
                        LIFECYCLE_BREAKOUT_CONFIRMED,
                        setup_family=OPENING_BREAKOUT,
                    )
                    direct += extra
            else:
                successor = self._successor_from_event(event, lifecycle)
                confirm = True
        elif event.event_type in {ENTRY_MISSED, FAILED_BREAKOUT, EXHAUSTION_RISK}:
            next_state = {
                ENTRY_MISSED: LIFECYCLE_ENTRY_MISSED,
                FAILED_BREAKOUT: LIFECYCLE_FAILED_BREAKOUT,
                EXHAUSTION_RISK: LIFECYCLE_EXHAUSTION_RISK,
            }[event.event_type]
            if next_state in LEGAL_TRANSITIONS.get(lifecycle.current_state, frozenset()):
                transition = LifecycleTransitionInput(
                    next_state=next_state,
                    reason=event.reason,
                    evidence_fingerprint=event.fingerprint,
                    source_identity=SOURCE_IDENTITY,
                    material_delta_kind=SETUP_STATE_CHANGED,
                )
        elif event.event_type in {PULLBACK_FORMING, RECLAIM_CONFIRMED}:
            if lifecycle.current_state in {
                LIFECYCLE_ENTRY_MISSED,
                LIFECYCLE_FAILED_BREAKOUT,
                LIFECYCLE_INVALIDATED,
            }:
                successor = self._successor_from_event(event, lifecycle)

        return NaturalCompositionStep(
            member_input=CompositionMemberInput(
                universe_member_id=base_input.universe_member_id,
                canonical_evidence=base_input.canonical_evidence,
                rvol_evidence=base_input.rvol_evidence,
                lifecycle=lifecycle,
                lifecycle_transition=transition,
                successor_setup=successor,
                existing_plan=existing,
            ),
            material_fingerprints=material,
            event_id=event.event_id,
            event_type=event.event_type,
            event_fingerprint=event.fingerprint,
            direct_transition_count=direct,
            confirm_breakout_after_commit=confirm,
        )

    def _event_observation_fingerprint(
        self,
        event: SequentialBreakoutEvent,
        member: HotUniverseMember,
        cutoff: datetime,
    ) -> str:
        match = next(
            (
                item
                for item in self._observations(member, cutoff=cutoff)
                if item.provider_timestamp == event.provider_timestamp
                and item.source_evidence_fingerprint
                == event.source_evidence_fingerprint
            ),
            None,
        )
        if match is None:
            raise ContinuousNaturalSetupError(
                "Sequential event omitted its completed canonical-bar observation."
            )
        return match.fingerprint

    def _unchanged_step(
        self,
        base_input: CompositionMemberInput,
        lifecycle: CandidateLifecycleSnapshot,
        request_material_fingerprint: str,
        *,
        event_type: str = UNKNOWN_EVENT,
        material_fingerprints: tuple[str, ...] = (),
    ) -> NaturalCompositionStep:
        existing = self.latest_plan(base_input.universe_member_id, lifecycle.current_setup_id)
        material = tuple(
            dict.fromkeys((request_material_fingerprint, *material_fingerprints))
        )[:MAX_MATERIAL_EXTENSIONS]
        return NaturalCompositionStep(
            member_input=CompositionMemberInput(
                universe_member_id=base_input.universe_member_id,
                canonical_evidence=base_input.canonical_evidence,
                rvol_evidence=base_input.rvol_evidence,
                lifecycle=lifecycle,
                existing_plan=existing,
            ),
            material_fingerprints=material,
            event_id="",
            event_type=event_type,
            event_fingerprint="",
        )

    def _successor_from_event(
        self,
        event: SequentialBreakoutEvent,
        lifecycle: CandidateLifecycleSnapshot,
    ) -> SuccessorSetupEvidence | None:
        if event.setup_family not in {CONTINUATION_BREAKOUT, PULLBACK, RECLAIM}:
            return None
        entry = float(event.trigger_price or 0.0)
        structural_range = float(event.prior_range_value or 0.0)
        if entry <= 0.0 or structural_range <= 0.0 or structural_range >= entry:
            return None
        stop = entry - structural_range
        target = entry + 2.0 * structural_range
        predecessor = (
            lifecycle.current_setup_id
            if lifecycle.current_state
            in {LIFECYCLE_ENTRY_MISSED, LIFECYCLE_FAILED_BREAKOUT, LIFECYCLE_INVALIDATED}
            else ""
        )
        payload = {
            "eventId": event.event_id,
            "eventFingerprint": event.fingerprint,
            "family": event.setup_family,
            "knownAt": event.receipt_timestamp,
            "entry": entry,
            "stop": stop,
            "target": target,
            "predecessorSetupId": predecessor,
            "predecessorState": lifecycle.current_state if predecessor else "",
            "levelKind": LEVEL_KIND,
        }
        fingerprint = _fingerprint("continuous-natural-successor-v1", payload)
        return SuccessorSetupEvidence(
            evidence_id=f"continuous-natural-successor-{fingerprint[:24]}",
            evidence_fingerprint=fingerprint,
            symbol=event.symbol,
            session_date=event.session_date,
            setup_family=event.setup_family,
            known_at=event.receipt_timestamp,
            source_level_kind=LEVEL_KIND,
            planned_entry=entry,
            stop_price=stop,
            target_prices=(target,),
            source_evidence_ids=(event.event_id, event.source_evidence_fingerprint),
            predecessor_setup_id=predecessor,
            predecessor_terminal_state=(lifecycle.current_state if predecessor else ""),
            successor_reason=(
                "DISTINCT_COMPLETED_BAR_SUCCESSOR_AFTER_TERMINAL_PREDECESSOR"
                if predecessor
                else "PROSPECTIVE_COMPLETED_BAR_CONTINUATION_SETUP"
            ),
        )

    def _apply_direct_event(
        self,
        event: SequentialBreakoutEvent,
        lifecycle: CandidateLifecycleSnapshot,
        next_state: str,
        *,
        setup_family: str = "",
        create_new_setup: bool = False,
    ) -> tuple[CandidateLifecycleSnapshot, int]:
        if next_state not in CANDIDATE_STATES:
            raise ContinuousNaturalSetupError("Natural lifecycle state is unsupported.")
        if next_state not in LEGAL_TRANSITIONS.get(lifecycle.current_state, frozenset()):
            return lifecycle, 0
        result = self.lifecycle.transition(
            opportunity_id=lifecycle.opportunity_id,
            next_state=next_state,
            evidence_fingerprint=_transition_evidence_fingerprint(
                event.fingerprint,
                next_state,
            ),
            source_identity=SOURCE_IDENTITY,
            occurred_at=_parse_timestamp(event.receipt_timestamp),
            provider_timestamp=_parse_timestamp(event.provider_timestamp),
            receipt_timestamp=_parse_timestamp(event.receipt_timestamp),
            reason=event.reason,
            material_delta_kind=SETUP_STATE_CHANGED,
            setup_family=setup_family,
            create_new_setup=create_new_setup,
        )
        if result.snapshot is None:
            raise ContinuousNaturalSetupError("Natural lifecycle transition returned no state.")
        return result.snapshot, int(result.event is not None)

    def _apply_proposal(self, proposal: object) -> None:
        self.lifecycle.transition(
            opportunity_id=str(getattr(proposal, "opportunity_id")),
            next_state=str(getattr(proposal, "next_state")),
            evidence_fingerprint=str(getattr(proposal, "evidence_fingerprint")),
            source_identity=str(getattr(proposal, "source_identity")),
            occurred_at=_parse_timestamp(str(getattr(proposal, "occurred_at"))),
            provider_timestamp=_parse_timestamp(
                str(getattr(proposal, "provider_timestamp"))
            ),
            receipt_timestamp=_parse_timestamp(
                str(getattr(proposal, "receipt_timestamp"))
            ),
            reason=str(getattr(proposal, "reason")),
            material_delta_kind=str(getattr(proposal, "material_delta_kind")),
            setup_family=str(getattr(proposal, "setup_family")),
            create_new_setup=bool(getattr(proposal, "create_new_setup")),
        )

    def _observations(self, member: HotUniverseMember, *, cutoff: datetime):
        snapshot = self._finality_snapshot(member, cutoff=cutoff)
        versions = tuple(
            item
            for item in snapshot.versions
            if item.bar.session_date == member.session_date
            and datetime.strptime("09:30", "%H:%M").time()
            <= _parse_timestamp(item.bar.timestamp).astimezone(EASTERN_TZ).time()
            < datetime.strptime("16:00", "%H:%M").time()
        )
        observations = []
        for version in versions:
            bar = version.bar
            observations.append(
                observation_from_canonical_bar(
                    bar,
                    receipt_timestamp=version.first_received_at,
                    observation_mode=(
                        PROSPECTIVE
                        if _parse_timestamp(bar.timestamp)
                        >= self._prospective_floor(member)
                        else HISTORICAL_REPLAY
                    ),
                )
            )
        return tuple(observations)

    def _finality_snapshot(
        self, member: HotUniverseMember, *, cutoff: datetime
    ) -> CanonicalMinuteFinalitySnapshot:
        return load_canonical_minute_finality_as_of(
            cutoff=cutoff,
            store_root=self.minute_store_root,
            symbols=(member.symbol,),
        )

    def _member_records(self, member_id: str) -> tuple[ContinuousProducerRecord, ...]:
        return tuple(
            item for item in self.producer_store.load() if item.member_id == member_id
        )

    def _processed_event_fingerprints(self, member_id: str) -> set[str]:
        values: set[str] = set()
        for record in self._member_records(member_id):
            payload = json.loads(record.payload_json)
            extensions = payload.get("materialExtensionFingerprints", [])
            if isinstance(extensions, list):
                values.update(str(item) for item in extensions)
        return values

    def _processed_material_fingerprints(self, member_id: str = "") -> set[str]:
        records: Iterable[ContinuousProducerRecord] = self.producer_store.load()
        if member_id:
            records = (item for item in records if item.member_id == member_id)
        values: set[str] = set()
        for record in records:
            payload = json.loads(record.payload_json)
            extensions = payload.get("materialExtensionFingerprints", [])
            if isinstance(extensions, list):
                values.update(str(item) for item in extensions)
        return values

    def _prospective_floor(self, member: HotUniverseMember) -> datetime:
        member_observed = _parse_timestamp(member.first_observed_at)
        if self._member_records(member.member_id):
            return member_observed
        return max(member_observed, self.runtime_started_at)

    def _authoritative_paths(self) -> dict[str, Path]:
        return {
            "candidateLifecycle": self.lifecycle.store.path,
            "sequentialBreakout": self.breakouts.path,
            "producer": self.producer_store.path,
        }

    def _recover_interrupted_composition(self) -> None:
        journal = self.producer_store.path.parent / _COMPOSITION_JOURNAL
        if not journal.exists():
            return
        try:
            payload = json.loads(journal.read_text(encoding="ascii"))
            transaction_name = str(payload.get("transactionDirectory", ""))
            entries = payload.get("targets")
            if (
                not transaction_name.startswith(_COMPOSITION_TRANSACTION_PREFIX)
                or Path(transaction_name).name != transaction_name
                or not isinstance(entries, Mapping)
                or set(entries) != set(self._authoritative_paths())
            ):
                raise ContinuousNaturalSetupError(
                    "Interrupted composition journal is invalid."
                )
            transaction_root = journal.parent / transaction_name
            for key, target in self._authoritative_paths().items():
                entry = entries.get(key)
                if not isinstance(entry, Mapping):
                    raise ContinuousNaturalSetupError(
                        "Interrupted composition journal target is invalid."
                    )
                existed = bool(entry.get("originalExists"))
                backup_name = str(entry.get("backupFile", ""))
                if Path(backup_name).name != backup_name:
                    raise ContinuousNaturalSetupError(
                        "Interrupted composition backup identity is invalid."
                    )
                original = (
                    (transaction_root / backup_name).read_bytes()
                    if existed
                    else None
                )
                _replace_exact(target, original)
            journal.unlink(missing_ok=True)
            shutil.rmtree(transaction_root, ignore_errors=True)
        except ContinuousNaturalSetupError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContinuousNaturalSetupError(
                "Interrupted composition could not be rolled back safely."
            ) from exc

    def _commit_preview(self, preview: "NaturalCompositionPreview") -> None:
        authoritative = self._authoritative_paths()
        staged = preview.staged_paths
        lease = PathTransactionLease(
            self.producer_store.path.parent / ".continuous-natural-composition"
        )
        with lease.transaction():
            for key, target in authoritative.items():
                if _optional_bytes(target) != preview.original_payloads[key]:
                    raise ContinuousNaturalSetupError(
                        "Authoritative composition state changed during preview."
                    )
            transaction_id = uuid.uuid4().hex
            transaction_root = (
                self.producer_store.path.parent
                / f"{_COMPOSITION_TRANSACTION_PREFIX}{transaction_id}"
            )
            transaction_root.mkdir(parents=True, exist_ok=False)
            journal = self.producer_store.path.parent / _COMPOSITION_JOURNAL
            target_entries: dict[str, object] = {}
            cleanup_transaction = True
            try:
                for index, key in enumerate(authoritative):
                    original = preview.original_payloads[key]
                    staged_payload = _optional_bytes(staged[key])
                    backup_name = f"original-{index}.bin"
                    staged_name = f"staged-{index}.bin"
                    if original is not None:
                        _replace_exact(transaction_root / backup_name, original)
                    if staged_payload is not None:
                        _replace_exact(transaction_root / staged_name, staged_payload)
                    target_entries[key] = {
                        "originalExists": original is not None,
                        "originalSha256": _optional_sha256(original),
                        "stagedExists": staged_payload is not None,
                        "stagedSha256": _optional_sha256(staged_payload),
                        "backupFile": backup_name,
                        "stagedFile": staged_name,
                    }
                _replace_exact(
                    journal,
                    _canonical_bytes(
                        {
                            "schemaVersion": 1,
                            "transactionId": transaction_id,
                            "transactionDirectory": transaction_root.name,
                            "targets": target_entries,
                        }
                    ),
                )
                for key, target in authoritative.items():
                    _replace_exact(target, _optional_bytes(staged[key]))
                self.lifecycle.store.load()
                self.breakouts.load()
                self.producer_store.load()
            except Exception as exc:
                rollback_error: Exception | None = None
                try:
                    for key, target in authoritative.items():
                        _replace_exact(target, preview.original_payloads[key])
                except Exception as rollback_exc:  # pragma: no cover - catastrophic I/O.
                    rollback_error = rollback_exc
                if rollback_error is not None:
                    cleanup_transaction = False
                    raise ContinuousNaturalSetupError(
                        "Composition publication and rollback both failed."
                    ) from rollback_error
                raise ContinuousNaturalSetupError(
                    "Composition publication failed and authoritative state was restored."
                ) from exc
            finally:
                if cleanup_transaction:
                    journal.unlink(missing_ok=True)
                    shutil.rmtree(transaction_root, ignore_errors=True)


class NaturalCompositionPreview:
    """Disposable state clone that publishes only after full evaluation succeeds."""

    def __init__(self, owner: ContinuousNaturalSetupCoordinator) -> None:
        self.owner = owner
        self._temporary = tempfile.TemporaryDirectory(
            prefix="MomentumHunter-Continuous-Composition-Preview-"
        )
        root = Path(self._temporary.name)
        natural_root = root / "natural"
        producer_store = ContinuousTradePlanProducerStore(root / "producer.json")
        self.original_payloads = {
            key: _optional_bytes(path)
            for key, path in owner._authoritative_paths().items()
        }
        self.original_state_identity = _fingerprint(
            "continuous-natural-authoritative-state-v1",
            {
                key: _optional_sha256(payload)
                for key, payload in self.original_payloads.items()
            },
        )
        staged_targets = {
            "candidateLifecycle": natural_root / "candidate-lifecycle.json",
            "sequentialBreakout": natural_root / "sequential-breakout.json",
            "producer": producer_store.path,
        }
        for key, payload in self.original_payloads.items():
            _replace_exact(staged_targets[key], payload)
        self.coordinator = ContinuousNaturalSetupCoordinator(
            root=natural_root,
            minute_store_root=owner.minute_store_root,
            producer_store=producer_store,
            runtime_started_at=owner.runtime_started_at,
        )
        self.producer_store = producer_store
        self.staged_paths = staged_targets
        self.committed = False

    def __enter__(self) -> "NaturalCompositionPreview":
        return self

    def commit(self) -> None:
        if self.committed:
            raise ContinuousNaturalSetupError(
                "Natural composition preview was already committed."
            )
        self.owner._commit_preview(self)
        self.committed = True

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc is not None:
            setattr(exc, "staging_began", True)
            setattr(exc, "authoritative_state_changed", self.committed)
            setattr(
                exc,
                "predecessor_lifecycle_identity",
                self.original_state_identity,
            )
            current = {
                key: _optional_bytes(path)
                for key, path in self.owner._authoritative_paths().items()
            }
            setattr(
                exc,
                "current_lifecycle_identity",
                _fingerprint(
                    "continuous-natural-authoritative-state-v1",
                    {
                        key: _optional_sha256(payload)
                        for key, payload in current.items()
                    },
                ),
            )
        self._temporary.cleanup()


def _optional_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _optional_sha256(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("ascii")


def _replace_exact(path: Path, payload: bytes | None) -> None:
    if payload is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _intraday_plan_from_wire(payload: Mapping[str, object]) -> IntradayPlanEvidence:
    values = dict(payload)
    for key in ("target_prices", "source_evidence_ids", "findings"):
        raw = values.get(key, ())
        if isinstance(raw, list):
            values[key] = tuple(raw)
    try:
        return IntradayPlanEvidence(**values)
    except (TypeError, ValueError) as exc:
        raise ContinuousNaturalSetupError(
            "Preserved producer TradePlan evidence is invalid."
        ) from exc


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuousNaturalSetupError("Natural setup timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousNaturalSetupError("Natural setup timestamp must be timezone-aware.")
    return parsed


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContinuousNaturalSetupError(f"{label} must be timezone-aware.")
    return value


def _transition_evidence_fingerprint(event_fingerprint: str, next_state: str) -> str:
    return _fingerprint(
        "continuous-natural-lifecycle-transition-v1",
        {
            "eventFingerprint": event_fingerprint,
            "nextState": next_state,
        },
    )


def _sha_or_fingerprint(value: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) == 64 and all(item in "0123456789abcdef" for item in normalized):
        return normalized
    return _fingerprint("continuous-member-origin-v1", normalized)


def _fingerprint(domain: str, value: object) -> str:
    payload = json.dumps(
        {"domain": domain, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=lambda item: asdict(item),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "CompletedBarMaterialEvent",
    "ContinuousNaturalSetupCoordinator",
    "ContinuousNaturalSetupError",
    "NaturalCompositionPreview",
    "NaturalCompositionStep",
    "NATURAL_SETUP_PROFILE",
]
