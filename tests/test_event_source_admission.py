from __future__ import annotations

import ast
import json
import multiprocessing
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_FORMING,
    DATA_STALE,
    DISCOVERED,
    WATCHING,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_plan_version import (
    PLAN_BLOCKED,
    ContinuousPlanLedger,
    evidence_fingerprint,
    plan_fingerprint_payload,
    validate_plan_version,
)
from momentum_hunter.event_driven_decision_cycle import (
    CANDIDATE_STATE_CHANGED,
    CREATED,
    CYCLE_CREATED,
    DATA_BECAME_STALE,
    MATERIAL,
    PLAN_INVALIDATED,
    PLAN_MATERIAL_REVISION,
    EventDecisionCycleCoordinator,
    EventDecisionCycleError,
    EventDecisionCycleStore,
    build_decision_trigger,
)
from momentum_hunter.event_source_admission import (
    CANDIDATE_LIFECYCLE_SOURCE,
    CANDIDATE_REFRESH_THROUGH_PLAN,
    CONTINUOUS_PLAN_SOURCE,
    EXACT_CANDIDATE_EVENT,
    EXACT_PLAN_SUCCESSOR,
    PLAN_SUCCESSOR_BLOCKED,
    RuntimeSourceAdmission,
    RuntimeSourceAdmissionError,
    RuntimeSourceAdmissionLedger,
    RuntimeSourceAdmissionStore,
    admit_runtime_trigger_source,
    validate_runtime_source_admission_ledger,
    validate_runtime_source_admission,
)
from momentum_hunter.intraday_trade_plan import CONTINUATION_BREAKOUT
from tests.test_event_driven_decision_cycle import (
    BASE,
    CONFIGURATION,
    synthetic_decision,
    synthetic_plan,
    synthetic_policy,
)


PROGRAM = "engineering-shadow-025"


def _append_source_admission_worker(
    path_text: str,
    admission: RuntimeSourceAdmission,
    start_event,
    output_queue,
) -> None:
    try:
        if not start_event.wait(10):
            raise RuntimeError("Synthetic source-admission start gate timed out.")
        stored = RuntimeSourceAdmissionStore(
            Path(path_text),
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
        ).append(admission)
        output_queue.put(("OK", stored.admission_id))
    except Exception as exc:  # pragma: no cover - asserted by parent process
        output_queue.put(("ERROR", type(exc).__name__, str(exc)))


def _hold_source_admission_lease_worker(
    path_text: str,
    ready_event,
    release_event,
    output_queue,
) -> None:
    try:
        store = RuntimeSourceAdmissionStore(
            Path(path_text),
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
        )
        with store.transaction():
            ready_event.set()
            if not release_event.wait(10):
                raise RuntimeError("Synthetic source-admission release gate timed out.")
        output_queue.put(("OK",))
    except Exception as exc:  # pragma: no cover - asserted by parent process
        output_queue.put(("ERROR", type(exc).__name__, str(exc)))


def _exit_while_holding_source_admission_lease_worker(
    path_text: str,
    ready_event,
) -> None:
    store = RuntimeSourceAdmissionStore(
        Path(path_text),
        evidence_program_id=PROGRAM,
        configuration_fingerprint=CONFIGURATION,
    )
    with store.transaction():
        ready_event.set()
        os._exit(29)


class EventSourceAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.candidate_policy = CandidateLifecyclePolicy(
            policy_version="synthetic-candidate-v1",
            cooldown_seconds=30,
            hysteresis_profile="synthetic-hysteresis-v1",
            minimum_delta_profile="synthetic-material-delta-v1",
        )
        self.candidate_store = CandidateLifecycleStore(
            self.root / "candidates.json"
        )
        self.candidates = CandidateLifecycleCoordinator(
            self.candidate_store,
            policy=self.candidate_policy,
        )
        self.event_policy = synthetic_policy(
            allowed_trigger_types=tuple(
                sorted(
                    {
                        CANDIDATE_STATE_CHANGED,
                        DATA_BECAME_STALE,
                        PLAN_INVALIDATED,
                        PLAN_MATERIAL_REVISION,
                    }
                )
            )
        )

    def source_store(self, path: Path, **changes):
        values = {
            "evidence_program_id": PROGRAM,
            "configuration_fingerprint": CONFIGURATION,
        }
        values.update(changes)
        return RuntimeSourceAdmissionStore(path, **values)

    def admit_source(self, **arguments):
        plan = arguments["plan_version"]
        previous = arguments.get("previous_plan_version")
        arguments["plan_ledger"] = ContinuousPlanLedger(
            plans=(previous, plan) if previous is not None else (plan,)
        )
        if arguments.get("candidate_event") is not None:
            arguments["candidate_ledger"] = self.candidate_store.load()
        return admit_runtime_trigger_source(**arguments)

    def setup_event(self):
        discovered = self.candidates.discover(
            symbol="AAA",
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="1" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=8),
            provider_timestamp=BASE - timedelta(minutes=8, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=8),
            reason="Synthetic candidate discovery.",
        )
        opportunity = discovered.snapshot.opportunity_id
        self.candidates.transition(
            opportunity_id=opportunity,
            next_state=WATCHING,
            evidence_fingerprint="2" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=7),
            provider_timestamp=BASE - timedelta(minutes=7, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=7),
            reason="Monitoring began.",
            material_delta_kind="MONITORING_ACTIVATED",
        )
        result = self.candidates.transition(
            opportunity_id=opportunity,
            next_state=BREAKOUT_FORMING,
            evidence_fingerprint="4" * 64,
            source_identity="synthetic-candles",
            occurred_at=BASE - timedelta(minutes=6),
            provider_timestamp=BASE - timedelta(minutes=6, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=6),
            reason="Breakout structure became material.",
            material_delta_kind="SETUP_IDENTITY_CHANGED",
            setup_family=CONTINUATION_BREAKOUT,
            create_new_setup=True,
        )
        return result.event

    def other_setup_event(self):
        discovered = self.candidates.discover(
            symbol="BBB",
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="a" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=5),
            provider_timestamp=BASE - timedelta(minutes=5, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=5),
            reason="Second synthetic candidate discovery.",
        )
        opportunity = discovered.snapshot.opportunity_id
        self.candidates.transition(
            opportunity_id=opportunity,
            next_state=WATCHING,
            evidence_fingerprint="b" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=4),
            provider_timestamp=BASE - timedelta(minutes=4, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=4),
            reason="Second candidate monitoring began.",
            material_delta_kind="MONITORING_ACTIVATED",
        )
        return self.candidates.transition(
            opportunity_id=opportunity,
            next_state=BREAKOUT_FORMING,
            evidence_fingerprint="c" * 64,
            source_identity="synthetic-candles",
            occurred_at=BASE - timedelta(minutes=3),
            provider_timestamp=BASE - timedelta(minutes=3, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=3),
            reason="Second breakout structure became material.",
            material_delta_kind="SETUP_IDENTITY_CHANGED",
            setup_family=CONTINUATION_BREAKOUT,
            create_new_setup=True,
        ).event

    def plan_for_event(self, event, *, previous=None, created_at=None):
        created_at = created_at or (
            BASE if previous is None else BASE + timedelta(minutes=1)
        )
        plan = synthetic_plan(
            created_at=created_at,
            candidate_state=event.next_state,
            candidate_event_id=event.event_id,
            candidate_evidence=event.evidence_fingerprint,
            opportunity_id=event.opportunity_id,
            setup_id=event.setup_id or "2" * 64,
            setup_evidence=event.evidence_fingerprint,
            version_number=1 if previous is None else previous.version_number + 1,
        )
        plan = replace(
            plan,
            symbol=event.symbol,
            session_date=event.session_date,
            setup_family=event.setup_family or plan.setup_family,
            setup_sequence=event.setup_sequence or plan.setup_sequence,
            candidate_policy_fingerprint=event.policy_fingerprint,
            candidate_updated_at=event.receipt_timestamp,
            predecessor_plan_version_id=(
                previous.plan_version_id if previous is not None else ""
            ),
            predecessor_plan_version_fingerprint=(
                previous.fingerprint if previous is not None else ""
            ),
            supersession_reason=(
                "CANDIDATE_EVIDENCE_REFRESH" if previous is not None else ""
            ),
        )
        return refingerprint_plan(plan)

    def test_setup_bound_candidate_transition_is_exact_runtime_source(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        before_event = asdict(event)
        before_plan = asdict(plan)

        admission = self.admit_source(
            plan_version=plan,
            event_cycle_policy=self.event_policy,
            candidate_event=event,
        )

        self.assertEqual(CANDIDATE_LIFECYCLE_SOURCE, admission.source_kind)
        self.assertEqual(EXACT_CANDIDATE_EVENT, admission.reason)
        self.assertEqual(CANDIDATE_STATE_CHANGED, admission.trigger.trigger_type)
        self.assertEqual(event.event_id, admission.source_record_id)
        self.assertEqual(event.event_id, admission.trigger.source_evidence_id)
        self.assertEqual(before_event, asdict(event))
        self.assertEqual(before_plan, asdict(plan))

    def test_candidate_stale_and_recovery_remain_exact_sources(self) -> None:
        setup = self.setup_event()
        stale = self.candidates.mark_stale(
            opportunity_id=setup.opportunity_id,
            evidence_fingerprint="5" * 64,
            source_identity="synthetic-candles",
            occurred_at=BASE - timedelta(minutes=4),
            provider_timestamp=BASE - timedelta(minutes=4, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=4),
            reason="Canonical candles became stale.",
        ).event
        stale_plan = self.plan_for_event(stale)
        stale_admission = self.admit_source(
            plan_version=stale_plan,
            event_cycle_policy=self.event_policy,
            candidate_event=stale,
        )
        self.assertEqual(DATA_STALE, stale_plan.candidate_state)
        self.assertEqual(DATA_BECAME_STALE, stale_admission.trigger.trigger_type)

        recovered = self.candidates.recover(
            opportunity_id=setup.opportunity_id,
            evidence_fingerprint="6" * 64,
            source_identity="synthetic-candles",
            occurred_at=BASE - timedelta(minutes=3),
            provider_timestamp=BASE - timedelta(minutes=3, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=3),
            reason="Canonical candles recovered.",
        ).event
        recovered_plan = self.plan_for_event(recovered)
        recovered_admission = self.admit_source(
            plan_version=recovered_plan,
            event_cycle_policy=self.event_policy,
            candidate_event=recovered,
        )
        self.assertEqual(BREAKOUT_FORMING, recovered_plan.candidate_state)
        self.assertEqual(
            CANDIDATE_STATE_CHANGED,
            recovered_admission.trigger.trigger_type,
        )

    def test_discovery_without_setup_bound_plan_is_rejected(self) -> None:
        discovered = self.candidates.discover(
            symbol="AAA",
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="7" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=2),
            provider_timestamp=BASE - timedelta(minutes=2, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=2),
            reason="Synthetic discovery without setup.",
        ).event
        plan = self.plan_for_event(discovered)
        self.assertEqual(DISCOVERED, plan.candidate_state)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "before a setup"):
            self.admit_source(
                plan_version=plan,
                event_cycle_policy=self.event_policy,
                candidate_event=discovered,
            )

    def test_watching_transition_without_setup_cannot_claim_plan_source(self) -> None:
        discovered = self.candidates.discover(
            symbol="AAA",
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="7" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=2),
            provider_timestamp=BASE - timedelta(minutes=2, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=2),
            reason="Synthetic discovery without setup.",
        )
        watching = self.candidates.transition(
            opportunity_id=discovered.snapshot.opportunity_id,
            next_state=WATCHING,
            evidence_fingerprint="8" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE - timedelta(minutes=1),
            provider_timestamp=BASE - timedelta(minutes=1, seconds=1),
            receipt_timestamp=BASE - timedelta(minutes=1),
            reason="Monitoring began without setup identity.",
            material_delta_kind="MONITORING_ACTIVATED",
        ).event
        plan = self.plan_for_event(watching)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "setup-bound"):
            self.admit_source(
                plan_version=plan,
                event_cycle_policy=self.event_policy,
                candidate_event=watching,
            )

    def test_plan_successor_is_the_single_context_change_source(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_id="regime-snapshot-2",
            regime_snapshot_fingerprint="a" * 64,
            regime_context_fingerprint="b" * 64,
        )
        admission = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        self.assertEqual(CONTINUOUS_PLAN_SOURCE, admission.source_kind)
        self.assertEqual(EXACT_PLAN_SUCCESSOR, admission.reason)
        self.assertEqual(PLAN_MATERIAL_REVISION, admission.trigger.trigger_type)
        self.assertEqual(current.plan_version_id, admission.source_record_id)
        self.assertEqual(current.fingerprint, admission.source_authority_fingerprint)
        self.assertEqual(current.created_at, admission.trigger.occurred_at)
        self.assertEqual(current.created_at, admission.trigger.receipt_timestamp)

    def test_blocked_successor_is_plan_invalidation_source(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            intraday_plan_execution_eligible=False,
            status=PLAN_BLOCKED,
            blockers=("INTRADAY_PLAN_NOT_EXECUTION_ELIGIBLE",),
        )
        admission = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        self.assertEqual(PLAN_SUCCESSOR_BLOCKED, admission.reason)
        self.assertEqual(PLAN_INVALIDATED, admission.trigger.trigger_type)

    def test_candidate_refresh_collapses_to_one_plan_successor_source(self) -> None:
        setup = self.setup_event()
        previous = self.plan_for_event(setup)
        refresh = self.candidates.discover(
            symbol="AAA",
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="9" * 64,
            source_identity="synthetic-monitor",
            occurred_at=BASE,
            provider_timestamp=BASE - timedelta(seconds=1),
            receipt_timestamp=BASE,
            reason="Candidate evidence refreshed without a state transition.",
        ).event
        current = self.plan_for_event(
            refresh,
            previous=previous,
            created_at=BASE + timedelta(minutes=1),
        )
        admission = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
            candidate_event=refresh,
        )
        self.assertEqual(CONTINUOUS_PLAN_SOURCE, admission.source_kind)
        self.assertEqual(CANDIDATE_REFRESH_THROUGH_PLAN, admission.reason)
        self.assertEqual(PLAN_MATERIAL_REVISION, admission.trigger.trigger_type)
        self.assertEqual("", admission.trigger.candidate_event_id)

    def test_missing_or_wrong_candidate_event_fails_closed(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "requires its exact"):
            self.admit_source(
                plan_version=plan,
                event_cycle_policy=self.event_policy,
            )
        with self.assertRaises(ValueError):
            self.admit_source(
                plan_version=plan,
                event_cycle_policy=self.event_policy,
                candidate_event=replace(event, fingerprint="0" * 64),
            )

    def test_unpersisted_plan_or_candidate_source_fails_closed(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "canonical ledger"):
            admit_runtime_trigger_source(
                plan_version=plan,
                plan_ledger=ContinuousPlanLedger(),
                event_cycle_policy=self.event_policy,
                candidate_event=event,
                candidate_ledger=self.candidate_store.load(),
            )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "requires its canonical"):
            admit_runtime_trigger_source(
                plan_version=plan,
                plan_ledger=ContinuousPlanLedger(plans=(plan,)),
                event_cycle_policy=self.event_policy,
                candidate_event=event,
            )

    def test_successor_requires_exact_predecessor_and_chronology(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_fingerprint="a" * 64,
        )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "predecessor"):
            self.admit_source(
                plan_version=current,
                event_cycle_policy=self.event_policy,
            )
        wrong = synthetic_plan(candidate_evidence="e" * 64)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "exact predecessor"):
            self.admit_source(
                plan_version=current,
                previous_plan_version=wrong,
                event_cycle_policy=self.event_policy,
            )

    def test_successor_without_material_change_is_rejected(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(previous)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "no material"):
            self.admit_source(
                plan_version=current,
                previous_plan_version=previous,
                event_cycle_policy=self.event_policy,
            )

    def test_candidate_evidence_cannot_change_under_reused_event_id(self) -> None:
        previous = synthetic_plan()
        clocks = tuple(
            replace(item, evidence_fingerprint="a" * 64)
            if item.evidence_fingerprint == previous.setup_revision_fingerprint
            else item
            for item in previous.source_clocks
        )
        current = successor_plan(
            previous,
            candidate_evidence_fingerprint="a" * 64,
            setup_revision_fingerprint="a" * 64,
            source_clocks=clocks,
            source_clock_fingerprint=evidence_fingerprint(
                tuple(asdict(item) for item in clocks)
            ),
        )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "without a new"):
            self.admit_source(
                plan_version=current,
                previous_plan_version=previous,
                event_cycle_policy=self.event_policy,
            )

    def test_policy_configuration_and_trigger_allowlist_fail_closed(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_fingerprint="a" * 64,
        )
        wrong_configuration = synthetic_policy(
            configuration_fingerprint="f" * 64,
            allowed_trigger_types=(PLAN_MATERIAL_REVISION,),
        )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "configuration"):
            self.admit_source(
                plan_version=current,
                previous_plan_version=previous,
                event_cycle_policy=wrong_configuration,
            )
        disallowed = synthetic_policy(
            allowed_trigger_types=(CANDIDATE_STATE_CHANGED,),
        )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "does not admit"):
            self.admit_source(
                plan_version=current,
                previous_plan_version=previous,
                event_cycle_policy=disallowed,
            )

    def test_admission_is_deterministic_and_tamper_evident(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_fingerprint="a" * 64,
        )
        first = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        second = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        self.assertEqual(first, second)
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "identity|fingerprint"):
            validate_runtime_source_admission(
                replace(first, source_record_fingerprint="0" * 64)
            )

    def test_admitted_plan_source_creates_one_dormant_cycle(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_fingerprint="a" * 64,
        )
        admission = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        coordinator = EventDecisionCycleCoordinator(
            EventDecisionCycleStore(self.root / "event-cycles.json"),
            policy=self.event_policy,
        )
        result = coordinator.process(
            admission.trigger,
            recorded_at=BASE + timedelta(minutes=1, seconds=3),
            cycle_started_at=BASE + timedelta(minutes=1),
            plan_version=current,
            decision=synthetic_decision(
                current,
                decided_at=BASE + timedelta(minutes=1, seconds=2),
            ),
        )
        self.assertEqual(CREATED, result.status)
        self.assertEqual(CYCLE_CREATED, result.receipt.disposition)
        self.assertEqual(current.plan_version_id, result.cycle.plan_version_id)

    def test_generic_plan_fingerprint_requires_exact_plan_source_identity(self) -> None:
        previous = synthetic_plan()
        current = successor_plan(
            previous,
            regime_snapshot_fingerprint="a" * 64,
        )
        admission = self.admit_source(
            plan_version=current,
            previous_plan_version=previous,
            event_cycle_policy=self.event_policy,
        )
        bad_trigger = build_decision_trigger(
            trigger_type=admission.trigger.trigger_type,
            opportunity_id=current.opportunity_id,
            setup_id=current.setup_id,
            symbol=current.symbol,
            session_date=current.session_date,
            previous_candidate_state=previous.candidate_state,
            next_candidate_state=current.candidate_state,
            occurred_at=datetime.fromisoformat(admission.trigger.occurred_at),
            provider_timestamp=datetime.fromisoformat(
                admission.trigger.provider_timestamp
            ),
            receipt_timestamp=datetime.fromisoformat(
                admission.trigger.receipt_timestamp
            ),
            source_identity="synthetic-not-the-plan",
            source_evidence_id=current.plan_version_id,
            source_evidence_fingerprint=current.fingerprint,
            material_delta_kind="PLAN_VERSION_SUPERSEDED",
            materiality=MATERIAL,
        )
        coordinator = EventDecisionCycleCoordinator(
            EventDecisionCycleStore(self.root / "bad-source.json"),
            policy=self.event_policy,
        )
        with self.assertRaisesRegex(EventDecisionCycleError, "supplied plan version"):
            coordinator.process(
                bad_trigger,
                recorded_at=BASE + timedelta(minutes=1, seconds=3),
                cycle_started_at=BASE + timedelta(minutes=1),
                plan_version=current,
                decision=synthetic_decision(
                    current,
                    decided_at=BASE + timedelta(minutes=1, seconds=2),
                ),
            )

    def test_store_round_trip_exact_replay_and_deterministic_bytes(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        admission = self.admit_source(
            plan_version=plan,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        first_path = self.root / "admissions-a.json"
        second_path = self.root / "admissions-b.json"
        first_store = self.source_store(first_path)
        second_store = self.source_store(second_path)

        self.assertEqual(admission, first_store.append(admission))
        first_bytes = first_path.read_bytes()
        self.assertEqual(admission, first_store.append(admission))
        self.assertEqual(first_bytes, first_path.read_bytes())
        second_store.append(admission)

        self.assertEqual(first_bytes, second_path.read_bytes())
        self.assertEqual((admission,), first_store.load().admissions)
        self.assertTrue(first_store.lease_path.exists())

    def test_store_requires_complete_ordered_plan_lineage(self) -> None:
        event = self.setup_event()
        initial = self.plan_for_event(event)
        initial_admission = self.admit_source(
            plan_version=initial,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        successor = successor_plan(initial, regime_snapshot_fingerprint="d" * 64)
        successor_admission = self.admit_source(
            plan_version=successor,
            previous_plan_version=initial,
            event_cycle_policy=self.event_policy,
        )
        store = self.source_store(self.root / "admissions.json")

        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "orphan|out-of-order"):
            store.append(successor_admission)
        self.assertFalse(store.path.exists())

        store.append(initial_admission)
        store.append(successor_admission)
        self.assertEqual(
            (initial_admission, successor_admission),
            store.load().admissions,
        )

    def test_persisted_admission_tampering_is_detected(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        admission = self.admit_source(
            plan_version=plan,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        store = self.source_store(self.root / "admissions.json")
        store.append(admission)
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        payload["admissions"][0]["reason"] = "TAMPERED"
        store.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "identity|fingerprint"):
            store.load()

    def test_store_rejects_cross_program_or_configuration_reuse(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        admission = self.admit_source(
            plan_version=plan,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        path = self.root / "admissions.json"
        self.source_store(path).append(admission)

        for store in (
            self.source_store(path, evidence_program_id="official-shadow-025"),
            self.source_store(path, configuration_fingerprint="d" * 64),
        ):
            with self.subTest(store=store):
                with self.assertRaisesRegex(
                    RuntimeSourceAdmissionError,
                    "namespace",
                ):
                    store.load()

    def test_ledger_namespace_header_tampering_is_detected(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        admission = self.admit_source(
            plan_version=plan,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        store = self.source_store(self.root / "admissions.json")
        store.append(admission)
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        payload["evidence_program_id"] = "official-shadow-025"
        store.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "fingerprint"):
            store.load()

    def test_atomic_replace_failure_preserves_previous_ledger(self) -> None:
        event = self.setup_event()
        initial = self.plan_for_event(event)
        initial_admission = self.admit_source(
            plan_version=initial,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        successor = successor_plan(initial, regime_snapshot_fingerprint="d" * 64)
        successor_admission = self.admit_source(
            plan_version=successor,
            previous_plan_version=initial,
            event_cycle_policy=self.event_policy,
        )
        store = self.source_store(self.root / "admissions.json")
        store.append(initial_admission)

        with patch(
            "momentum_hunter.event_source_admission.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaises(OSError):
                store.append(successor_admission)

        self.assertEqual((initial_admission,), store.load().admissions)
        self.assertEqual([], list(self.root.glob("*.tmp")))

    def test_two_processes_do_not_lose_distinct_admissions(self) -> None:
        first_event = self.setup_event()
        second_event = self.other_setup_event()
        first_plan = self.plan_for_event(first_event)
        second_plan = self.plan_for_event(second_event)
        first = self.admit_source(
            plan_version=first_plan,
            candidate_event=first_event,
            event_cycle_policy=self.event_policy,
        )
        second = self.admit_source(
            plan_version=second_plan,
            candidate_event=second_event,
            event_cycle_policy=self.event_policy,
        )
        path = self.root / "admissions.json"
        context = multiprocessing.get_context("spawn")
        start_event = context.Event()
        output_queue = context.Queue()
        processes = [
            context.Process(
                target=_append_source_admission_worker,
                args=(str(path), admission, start_event, output_queue),
            )
            for admission in (first, second)
        ]
        for process in processes:
            process.start()
        start_event.set()
        results = [output_queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)

        self.assertEqual({"OK"}, {item[0] for item in results})
        self.assertEqual({0}, {process.exitcode for process in processes})
        self.assertEqual(
            {first.admission_id, second.admission_id},
            {
                item.admission_id
                for item in self.source_store(path).load().admissions
            },
        )

    def test_cross_process_lease_timeout_is_finite_and_recovers(self) -> None:
        path = self.root / "admissions.json"
        context = multiprocessing.get_context("spawn")
        ready_event = context.Event()
        release_event = context.Event()
        output_queue = context.Queue()
        process = context.Process(
            target=_hold_source_admission_lease_worker,
            args=(str(path), ready_event, release_event, output_queue),
        )
        process.start()
        self.assertTrue(ready_event.wait(10))
        try:
            contender = self.source_store(path, lease_timeout_seconds=0.1)
            with self.assertRaisesRegex(RuntimeSourceAdmissionError, "lease timed out"):
                with contender.transaction():
                    self.fail("Contender acquired an already-owned process lease.")
        finally:
            release_event.set()
            process.join(timeout=15)

        self.assertEqual(("OK",), output_queue.get(timeout=5))
        self.assertEqual(0, process.exitcode)
        with self.source_store(
            path,
            lease_timeout_seconds=1.0,
        ).transaction():
            pass

    def test_process_exit_releases_cross_process_lease(self) -> None:
        path = self.root / "admissions.json"
        context = multiprocessing.get_context("spawn")
        ready_event = context.Event()
        process = context.Process(
            target=_exit_while_holding_source_admission_lease_worker,
            args=(str(path), ready_event),
        )
        process.start()
        self.assertTrue(ready_event.wait(10))
        process.join(timeout=15)

        self.assertEqual(29, process.exitcode)
        with self.source_store(
            path,
            lease_timeout_seconds=1.0,
        ).transaction():
            pass

    def test_store_timeout_must_be_positive_and_finite(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    RuntimeSourceAdmissionError,
                    "positive and finite",
                ):
                    self.source_store(
                        self.root / "admissions.json",
                        lease_timeout_seconds=timeout,
                    )

    def test_store_requires_explicit_program_and_configuration_identity(self) -> None:
        with self.assertRaises(TypeError):
            RuntimeSourceAdmissionStore(self.root / "admissions.json")

    def test_ledger_rejects_duplicate_plan_and_source_identity(self) -> None:
        event = self.setup_event()
        plan = self.plan_for_event(event)
        admission = self.admit_source(
            plan_version=plan,
            candidate_event=event,
            event_cycle_policy=self.event_policy,
        )
        with self.assertRaisesRegex(RuntimeSourceAdmissionError, "duplicate identity"):
            validate_runtime_source_admission_ledger(
                RuntimeSourceAdmissionLedger(
                    evidence_program_id=PROGRAM,
                    configuration_fingerprint=CONFIGURATION,
                    admissions=(admission, admission),
                )
            )

    def test_module_has_no_network_broker_or_runtime_capability(self) -> None:
        module_root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        trees = [
            ast.parse((module_root / name).read_text(encoding="utf-8"))
            for name in ("event_source_admission.py", "path_transaction.py")
        ]
        imports = {
            alias.name.split(".")[0]
            for tree in trees
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(
            imports.isdisjoint(
                {
                    "requests",
                    "urllib",
                    "httpx",
                    "socket",
                    "websocket",
                    "subprocess",
                    "alpaca_paper",
                    "schwab_market_data",
                    "shadow_trading",
                }
            )
        )
        calls = {
            node.func.attr
            for tree in trees
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            calls.isdisjoint(
                {
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                }
            )
        )


def successor_plan(previous, **changes):
    created_at = BASE + timedelta(minutes=previous.version_number)
    provisional = replace(
        previous,
        plan_version_id="",
        fingerprint="",
        version_number=previous.version_number + 1,
        created_at=created_at.isoformat(),
        predecessor_plan_version_id=previous.plan_version_id,
        predecessor_plan_version_fingerprint=previous.fingerprint,
        supersession_reason="SYNTHETIC_MATERIAL_UPDATE",
        **changes,
    )
    return refingerprint_plan(provisional)


def refingerprint_plan(plan):
    provisional = replace(plan, plan_version_id="", fingerprint="")
    fingerprint = evidence_fingerprint(plan_fingerprint_payload(provisional))
    result = replace(
        provisional,
        plan_version_id=f"continuous-plan-{fingerprint[:24]}",
        fingerprint=fingerprint,
    )
    validate_plan_version(result)
    return result


if __name__ == "__main__":
    unittest.main()
