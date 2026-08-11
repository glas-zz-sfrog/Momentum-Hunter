from __future__ import annotations

import ast
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.candidate_lifecycle import (
    DATA_STALE,
    EXECUTION_ELIGIBLE,
    WATCHING,
)
from momentum_hunter.continuous_plan_version import (
    ALLOCATION_AUTHORIZED,
    ALLOCATION_BLOCKED,
    DECISION_AUTHORIZED,
    DECISION_NO_TRADE,
    EXECUTION_AUTHORITY,
    PLAN_BLOCKED,
    PROSPECTIVE_EVIDENCE_ONLY,
    READY_FOR_RISK_REVIEW,
    RISK_AUTHORIZED,
    RISK_BLOCKED,
    RVOL_EXECUTION_ELIGIBLE,
    ContinuousPlanDecision,
    ContinuousPlanError,
    ContinuousPlanVersion,
    SourceClockEvidence,
    decision_fingerprint_payload,
    evidence_fingerprint,
    plan_fingerprint_payload,
)
from momentum_hunter.event_driven_decision_cycle import (
    CANDIDATE_STATE_CHANGED,
    COOLDOWN_SUPPRESSED,
    CREATED,
    CYCLE_CREATED,
    DATA_BECAME_STALE,
    DUPLICATE,
    EVENT_WINDOW_STABILIZED,
    INSUFFICIENT_DELTA_IGNORED,
    INSIGNIFICANT,
    MARKET_REGIME_CHANGED,
    MATERIAL,
    MEANINGFUL_LEVEL_BREAK,
    NEW_CANDIDATE_DISCOVERED,
    NO_SELECTION,
    PLAN_MATERIAL_REVISION,
    QUOTE_ONLY,
    QUOTE_ONLY_IGNORED,
    QUOTE_UPDATE,
    SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION,
    SPREAD_BECAME_EXECUTABLE,
    TIME_NORMALIZED_VOLUME_ABNORMAL,
    DecisionTriggerEvidence,
    EventDecisionCycleCoordinator,
    EventDecisionCycleError,
    EventDecisionCycleLedger,
    EventDecisionCyclePolicy,
    EventDecisionCycleStore,
    build_decision_trigger,
    canonical_json_bytes,
    cycle_fingerprint,
    ledger_to_wire,
    receipt_fingerprint,
    validate_ledger,
    validate_policy,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    TECHNICAL_DRIVER,
)
from momentum_hunter.macro_event_context import NORMAL
from momentum_hunter.rolling_market_regime import RISK_ON, SUFFICIENT


SESSION = "2026-08-10"
SYMBOL = "AAA"
OPPORTUNITY = "1" * 64
SETUP = "2" * 64
INTRADAY_PLAN = "3" * 64
CANDIDATE_EVENT = "4" * 64
CANDIDATE_EVIDENCE = "5" * 64
SETUP_EVIDENCE = "6" * 64
RVOL_EVIDENCE = "7" * 64
REGIME_EVIDENCE = "8" * 64
EVENT_EVIDENCE = "9" * 64
QUOTE_EVIDENCE = "a" * 64
CONFIGURATION = "b" * 64
BASE = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)


def synthetic_plan(
    *,
    created_at: datetime = BASE,
    candidate_state: str = EXECUTION_ELIGIBLE,
    candidate_event_id: str = CANDIDATE_EVENT,
    candidate_evidence: str = CANDIDATE_EVIDENCE,
    opportunity_id: str = OPPORTUNITY,
    setup_id: str = SETUP,
    intraday_plan_id: str = INTRADAY_PLAN,
    intraday_plan_fingerprint: str = "c" * 64,
    setup_evidence: str = SETUP_EVIDENCE,
    version_number: int = 1,
) -> ContinuousPlanVersion:
    blockers = (
        ()
        if candidate_state == EXECUTION_ELIGIBLE
        else ("CANDIDATE_NOT_EXECUTION_ELIGIBLE",)
    )
    clocks = (
        SourceClockEvidence(
            source_identity="synthetic-setup",
            provider_timestamp=(created_at - timedelta(seconds=45)).isoformat(),
            receipt_timestamp=(created_at - timedelta(seconds=44)).isoformat(),
            evidence_fingerprint=setup_evidence,
        ),
        SourceClockEvidence(
            source_identity="synthetic-rvol",
            provider_timestamp=(created_at - timedelta(seconds=35)).isoformat(),
            receipt_timestamp=(created_at - timedelta(seconds=34)).isoformat(),
            evidence_fingerprint=RVOL_EVIDENCE,
        ),
        SourceClockEvidence(
            source_identity="synthetic-quote",
            provider_timestamp=(created_at - timedelta(seconds=15)).isoformat(),
            receipt_timestamp=(created_at - timedelta(seconds=14)).isoformat(),
            evidence_fingerprint=QUOTE_EVIDENCE,
        ),
    )
    source_clock_fingerprint = evidence_fingerprint(
        tuple(asdict(item) for item in clocks)
    )
    provisional = ContinuousPlanVersion(
        plan_version_id="",
        version_number=version_number,
        opportunity_id=opportunity_id,
        symbol=SYMBOL,
        session_date=SESSION,
        setup_id=setup_id,
        setup_family=CONTINUATION_BREAKOUT,
        setup_sequence=1,
        setup_revision_id="setup-revision-1",
        setup_revision_fingerprint=setup_evidence,
        setup_authority=EXECUTION_AUTHORITY,
        setup_driver=TECHNICAL_DRIVER,
        intraday_plan_id=intraday_plan_id,
        intraday_plan_fingerprint=intraday_plan_fingerprint,
        intraday_plan_execution_eligible=True,
        created_at=created_at.isoformat(),
        entry_expires_at=(created_at + timedelta(hours=1)).isoformat(),
        forced_flat_at=(created_at + timedelta(hours=6)).isoformat(),
        candidate_state=candidate_state,
        candidate_event_id=candidate_event_id,
        candidate_evidence_fingerprint=candidate_evidence,
        candidate_policy_fingerprint="d" * 64,
        candidate_updated_at=(created_at - timedelta(seconds=20)).isoformat(),
        regime_snapshot_id="regime-snapshot-1",
        regime_snapshot_fingerprint=REGIME_EVIDENCE,
        regime_context_fingerprint="e" * 64,
        regime_policy_fingerprint="f" * 64,
        regime_label=RISK_ON,
        regime_sufficiency=SUFFICIENT,
        event_context_id="event-context-1",
        event_context_fingerprint=EVENT_EVIDENCE,
        event_calendar_fingerprint="0" * 64,
        event_policy_fingerprint="1" * 64,
        event_status=NORMAL,
        catalyst_snapshot_id="",
        catalyst_snapshot_fingerprint="",
        catalyst_revision_id="",
        catalyst_revision_fingerprint="",
        catalyst_policy_fingerprint="",
        catalyst_authority="",
        catalyst_state="",
        catalyst_availability_status="",
        catalyst_is_duplicate=False,
        rvol_evidence_id="rvol-evidence-1",
        rvol_evidence_fingerprint=RVOL_EVIDENCE,
        rvol_authority_state=RVOL_EXECUTION_ELIGIBLE,
        source_clocks=clocks,
        source_clock_fingerprint=source_clock_fingerprint,
        predecessor_plan_version_id="",
        predecessor_plan_version_fingerprint="",
        supersession_reason="",
        policy_version="synthetic-plan-policy-v1",
        policy_fingerprint="2" * 64,
        configuration_fingerprint=CONFIGURATION,
        authority_profile=PROSPECTIVE_EVIDENCE_ONLY,
        status=READY_FOR_RISK_REVIEW if not blockers else PLAN_BLOCKED,
        blockers=blockers,
        warnings=(),
        fingerprint="",
    )
    fingerprint = evidence_fingerprint(plan_fingerprint_payload(provisional))
    return replace(
        provisional,
        plan_version_id=f"continuous-plan-{fingerprint[:24]}",
        fingerprint=fingerprint,
    )


def synthetic_decision(
    plan: ContinuousPlanVersion,
    *,
    decided_at: datetime | None = None,
    authorized: bool = True,
    nonce: str = "1",
) -> ContinuousPlanDecision:
    decided_at = decided_at or (
        datetime.fromisoformat(plan.created_at) + timedelta(seconds=2)
    )
    risk_fingerprint = evidence_fingerprint({"risk": nonce})
    allocation_fingerprint = evidence_fingerprint({"allocation": nonce})
    blockers = (
        ()
        if authorized
        else (
            *plan.blockers,
            "RISK_DECISION_BLOCKED",
            "ALLOCATION_DECISION_BLOCKED",
            "ALLOCATION_QUANTITY_NOT_POSITIVE",
            "SYNTHETIC_RISK_BLOCK",
        )
    )
    provisional = ContinuousPlanDecision(
        decision_id="",
        decided_at=decided_at.isoformat(),
        mode="ALPACA_PAPER_ENGINEERING",
        status=DECISION_AUTHORIZED if authorized else DECISION_NO_TRADE,
        plan_version_id=plan.plan_version_id,
        plan_version_fingerprint=plan.fingerprint,
        opportunity_id=plan.opportunity_id,
        setup_id=plan.setup_id,
        intraday_plan_id=plan.intraday_plan_id,
        risk_decision_id=f"synthetic-risk-{nonce}",
        risk_decision_fingerprint=risk_fingerprint,
        risk_policy_fingerprint="3" * 64,
        allocation_decision_cycle_id=f"synthetic-allocation-{nonce}",
        allocation_decision_fingerprint=allocation_fingerprint,
        allocation_policy_fingerprint="4" * 64,
        account_snapshot_fingerprint="5" * 64,
        capability_registry_fingerprint="6" * 64,
        final_authorized_quantity="0.25" if authorized else "0",
        plan_status=plan.status,
        plan_blockers=plan.blockers,
        risk_status=RISK_AUTHORIZED if authorized else RISK_BLOCKED,
        allocation_status=(
            ALLOCATION_AUTHORIZED if authorized else ALLOCATION_BLOCKED
        ),
        blockers=blockers,
        fingerprint="",
    )
    fingerprint = evidence_fingerprint(decision_fingerprint_payload(provisional))
    identity = evidence_fingerprint(
        {
            "plan_version_id": provisional.plan_version_id,
            "risk_decision_fingerprint": provisional.risk_decision_fingerprint,
            "allocation_decision_fingerprint": (
                provisional.allocation_decision_fingerprint
            ),
            "decided_at": provisional.decided_at,
        }
    )
    return replace(
        provisional,
        decision_id=f"continuous-decision-{identity[:24]}",
        fingerprint=fingerprint,
    )


def synthetic_policy(**changes) -> EventDecisionCyclePolicy:
    values = {
        "policy_version": "synthetic-event-cycle-v1",
        "configuration_fingerprint": CONFIGURATION,
        "cooldown_seconds": 300,
        "minimum_delta_profile": "material-evidence-v1",
        "allowed_trigger_types": tuple(
            sorted(
                {
                    CANDIDATE_STATE_CHANGED,
                    DATA_BECAME_STALE,
                    EVENT_WINDOW_STABILIZED,
                    MARKET_REGIME_CHANGED,
                    MEANINGFUL_LEVEL_BREAK,
                    NEW_CANDIDATE_DISCOVERED,
                    PLAN_MATERIAL_REVISION,
                    SPREAD_BECAME_EXECUTABLE,
                    TIME_NORMALIZED_VOLUME_ABNORMAL,
                }
            )
        ),
    }
    values.update(changes)
    return EventDecisionCyclePolicy(**values)


def synthetic_trigger(
    plan: ContinuousPlanVersion,
    *,
    trigger_type: str = CANDIDATE_STATE_CHANGED,
    materiality: str = MATERIAL,
    occurred_at: datetime | None = None,
    source_fingerprint: str | None = None,
    candidate_event_id: str | None = None,
    next_state: str | None = None,
    setup_id: str | None = None,
    source_evidence_id: str = "synthetic-source-1",
) -> DecisionTriggerEvidence:
    occurred_at = occurred_at or (
        datetime.fromisoformat(plan.created_at) - timedelta(seconds=30)
    )
    default_sources = {
        CANDIDATE_STATE_CHANGED: plan.candidate_evidence_fingerprint,
        NEW_CANDIDATE_DISCOVERED: plan.candidate_evidence_fingerprint,
        MEANINGFUL_LEVEL_BREAK: plan.setup_revision_fingerprint,
        PLAN_MATERIAL_REVISION: plan.intraday_plan_fingerprint,
        TIME_NORMALIZED_VOLUME_ABNORMAL: plan.rvol_evidence_fingerprint,
        MARKET_REGIME_CHANGED: plan.regime_snapshot_fingerprint,
        EVENT_WINDOW_STABILIZED: plan.event_context_fingerprint,
        SPREAD_BECAME_EXECUTABLE: QUOTE_EVIDENCE,
        DATA_BECAME_STALE: QUOTE_EVIDENCE,
        QUOTE_UPDATE: QUOTE_EVIDENCE,
    }
    return build_decision_trigger(
        trigger_type=trigger_type,
        opportunity_id=plan.opportunity_id,
        setup_id=plan.setup_id if setup_id is None else setup_id,
        symbol=plan.symbol,
        session_date=plan.session_date,
        previous_candidate_state=WATCHING,
        next_candidate_state=next_state or plan.candidate_state,
        occurred_at=occurred_at,
        provider_timestamp=occurred_at - timedelta(seconds=1),
        receipt_timestamp=occurred_at + timedelta(seconds=1),
        source_identity="synthetic-provider",
        source_evidence_id=source_evidence_id,
        source_evidence_fingerprint=(
            source_fingerprint or default_sources[trigger_type]
        ),
        material_delta_kind=f"{trigger_type}_DELTA",
        materiality=materiality,
        candidate_event_id=(
            plan.candidate_event_id
            if candidate_event_id is None
            and trigger_type
            in {CANDIDATE_STATE_CHANGED, NEW_CANDIDATE_DISCOVERED}
            else (candidate_event_id or "")
        ),
    )


class EventDrivenDecisionCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "cycles.json"
        self.policy = synthetic_policy()
        self.store = EventDecisionCycleStore(self.path)
        self.coordinator = EventDecisionCycleCoordinator(
            self.store, policy=self.policy
        )

    def process_cycle(
        self,
        *,
        plan: ContinuousPlanVersion | None = None,
        decision: ContinuousPlanDecision | None = None,
        trigger: DecisionTriggerEvidence | None = None,
        recorded_at: datetime | None = None,
    ):
        plan = plan or synthetic_plan()
        decision = decision or synthetic_decision(plan)
        trigger = trigger or synthetic_trigger(plan)
        return self.coordinator.process(
            trigger,
            cycle_started_at=datetime.fromisoformat(trigger.receipt_timestamp)
            + timedelta(milliseconds=100),
            recorded_at=recorded_at
            or datetime.fromisoformat(decision.decided_at) + timedelta(seconds=1),
            plan_version=plan,
            decision=decision,
        )

    def test_authorized_event_creates_nonlive_selection_without_execution(self) -> None:
        result = self.process_cycle()

        self.assertEqual(CREATED, result.status)
        self.assertEqual(CYCLE_CREATED, result.receipt.disposition)
        self.assertIsNotNone(result.cycle)
        assert result.cycle is not None
        self.assertEqual(
            SELECTED_FOR_DOWNSTREAM_NONLIVE_EXECUTION,
            result.cycle.selection_result,
        )
        self.assertTrue(result.cycle.selected)
        self.assertEqual("ALPACA_PAPER_ENGINEERING", result.cycle.mode)
        wire = ledger_to_wire(self.store.load())
        encoded = json.dumps(wire).lower()
        for forbidden in (
            "order_id",
            "broker_order",
            "submit_order",
            "cancel_order",
            "live_endpoint",
            "transmit",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_no_trade_preserves_blockers_and_no_selection(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan, authorized=False)
        result = self.process_cycle(plan=plan, decision=decision)

        assert result.cycle is not None
        self.assertEqual(NO_SELECTION, result.cycle.selection_result)
        self.assertEqual(DECISION_NO_TRADE, result.cycle.decision_status)
        self.assertEqual(decision.blockers, result.cycle.blockers)
        self.assertFalse(result.cycle.selected)

    def test_historical_plan_cannot_enter_event_cycle(self) -> None:
        plan = synthetic_plan()
        provisional = replace(
            plan,
            plan_version_id="",
            authority_profile="HISTORICAL_REPLAY",
            fingerprint="",
        )
        fingerprint = evidence_fingerprint(plan_fingerprint_payload(provisional))
        historical = replace(
            provisional,
            plan_version_id=f"continuous-plan-{fingerprint[:24]}",
            fingerprint=fingerprint,
        )

        with self.assertRaisesRegex(ContinuousPlanError, "not prospective"):
            self.process_cycle(
                plan=historical,
                decision=synthetic_decision(historical),
                trigger=synthetic_trigger(historical),
            )
        self.assertFalse(self.path.exists())

    def test_exact_replay_is_idempotent(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan)
        trigger = synthetic_trigger(plan)
        first = self.process_cycle(plan=plan, decision=decision, trigger=trigger)
        before = self.path.read_bytes()
        second = self.process_cycle(plan=plan, decision=decision, trigger=trigger)

        self.assertEqual(DUPLICATE, second.status)
        self.assertEqual(first.receipt, second.receipt)
        self.assertEqual(first.cycle, second.cycle)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(self.store.load().cycles))

    def test_same_trigger_cannot_bind_a_different_decision(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(plan)
        self.process_cycle(plan=plan, decision=synthetic_decision(plan), trigger=trigger)

        with self.assertRaisesRegex(EventDecisionCycleError, "contradicts"):
            self.process_cycle(
                plan=plan,
                decision=synthetic_decision(plan, nonce="2"),
                trigger=trigger,
            )

    def test_quote_update_is_recorded_but_does_not_create_cycle(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(
            plan, trigger_type=QUOTE_UPDATE, materiality=QUOTE_ONLY
        )
        result = self.coordinator.process(
            trigger,
            recorded_at=datetime.fromisoformat(trigger.receipt_timestamp)
            + timedelta(seconds=1),
        )

        self.assertEqual(QUOTE_ONLY_IGNORED, result.receipt.disposition)
        self.assertIsNone(result.cycle)
        self.assertEqual(0, len(self.store.load().cycles))

    def test_suppressed_trigger_cannot_carry_fabricated_decision_work(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(
            plan, trigger_type=QUOTE_UPDATE, materiality=QUOTE_ONLY
        )
        with self.assertRaisesRegex(EventDecisionCycleError, "suppressed"):
            self.coordinator.process(
                trigger,
                recorded_at=BASE + timedelta(seconds=4),
                cycle_started_at=BASE - timedelta(seconds=20),
                plan_version=plan,
                decision=synthetic_decision(plan),
            )

    def test_insignificant_delta_is_recorded_without_cycle(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(plan, materiality=INSIGNIFICANT)
        result = self.coordinator.process(
            trigger,
            recorded_at=BASE + timedelta(seconds=4),
        )

        self.assertEqual(INSUFFICIENT_DELTA_IGNORED, result.receipt.disposition)
        self.assertIsNone(result.cycle)

    def test_entry_seeking_trigger_is_suppressed_during_cooldown(self) -> None:
        first = self.process_cycle()
        assert first.cycle is not None
        later_plan = synthetic_plan(created_at=BASE + timedelta(seconds=120))
        trigger = synthetic_trigger(
            later_plan,
            trigger_type=MEANINGFUL_LEVEL_BREAK,
            source_evidence_id="second-level-break",
        )
        result = self.coordinator.process(
            trigger,
            recorded_at=BASE + timedelta(seconds=121),
        )

        self.assertEqual(COOLDOWN_SUPPRESSED, result.receipt.disposition)
        self.assertIsNone(result.cycle)
        self.assertEqual(first.cycle.cycle_id, result.receipt.predecessor_cycle_id)

    def test_regime_safety_reevaluation_bypasses_entry_cooldown(self) -> None:
        first = self.process_cycle()
        assert first.cycle is not None
        later_plan = synthetic_plan(created_at=BASE + timedelta(seconds=120))
        later_decision = synthetic_decision(later_plan, nonce="2")
        trigger = synthetic_trigger(
            later_plan,
            trigger_type=MARKET_REGIME_CHANGED,
            source_evidence_id="regime-change-2",
        )
        result = self.process_cycle(
            plan=later_plan,
            decision=later_decision,
            trigger=trigger,
        )

        assert result.cycle is not None
        self.assertEqual(2, result.cycle.sequence)
        self.assertEqual(first.cycle.cycle_id, result.cycle.predecessor_cycle_id)

    def test_candidate_stale_safety_reevaluation_bypasses_cooldown(self) -> None:
        first = self.process_cycle()
        assert first.cycle is not None
        later_plan = synthetic_plan(
            created_at=BASE + timedelta(seconds=120),
            candidate_state=DATA_STALE,
            candidate_event_id="8" * 64,
            candidate_evidence="9" * 64,
        )
        later_decision = synthetic_decision(later_plan, authorized=False, nonce="2")
        trigger = synthetic_trigger(
            later_plan,
            trigger_type=CANDIDATE_STATE_CHANGED,
            next_state=DATA_STALE,
            source_evidence_id="candidate-stale-2",
        )
        result = self.process_cycle(
            plan=later_plan,
            decision=later_decision,
            trigger=trigger,
        )

        assert result.cycle is not None
        self.assertEqual(2, result.cycle.sequence)

    def test_policy_disabled_trigger_fails_closed(self) -> None:
        policy = synthetic_policy(
            allowed_trigger_types=(CANDIDATE_STATE_CHANGED,)
        )
        coordinator = EventDecisionCycleCoordinator(self.store, policy=policy)
        plan = synthetic_plan()
        trigger = synthetic_trigger(plan, trigger_type=MEANINGFUL_LEVEL_BREAK)
        with self.assertRaisesRegex(EventDecisionCycleError, "not enabled"):
            coordinator.process(trigger, recorded_at=BASE + timedelta(seconds=3))

    def test_plan_configuration_mismatch_fails_closed(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan)
        trigger = synthetic_trigger(plan)
        coordinator = EventDecisionCycleCoordinator(
            self.store,
            policy=synthetic_policy(configuration_fingerprint="9" * 64),
        )

        with self.assertRaisesRegex(EventDecisionCycleError, "configuration"):
            coordinator.process(
                trigger,
                cycle_started_at=datetime.fromisoformat(trigger.receipt_timestamp)
                + timedelta(milliseconds=100),
                recorded_at=BASE + timedelta(seconds=3),
                plan_version=plan,
                decision=decision,
            )
        self.assertFalse(self.path.exists())

    def test_trigger_source_must_be_frozen_by_plan(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(plan, source_fingerprint="0" * 64)
        with self.assertRaisesRegex(EventDecisionCycleError, "not frozen"):
            self.process_cycle(plan=plan, trigger=trigger)

    def test_candidate_trigger_event_must_match_plan(self) -> None:
        plan = synthetic_plan()
        trigger = synthetic_trigger(plan, candidate_event_id="0" * 64)
        with self.assertRaisesRegex(EventDecisionCycleError, "event does not match"):
            self.process_cycle(plan=plan, trigger=trigger)

    def test_opportunity_identity_mismatch_fails_closed(self) -> None:
        plan = synthetic_plan()
        trigger = replace(synthetic_trigger(plan), opportunity_id="0" * 64)
        with self.assertRaisesRegex(EventDecisionCycleError, "fingerprint"):
            self.process_cycle(plan=plan, trigger=trigger)

    def test_continuous_decision_must_bind_plan(self) -> None:
        plan = synthetic_plan()
        other = synthetic_plan(intraday_plan_id="0" * 64)
        decision = synthetic_decision(other)
        with self.assertRaisesRegex(EventDecisionCycleError, "supplied plan"):
            self.process_cycle(plan=plan, decision=decision)

    def test_decision_cannot_forge_blocked_plan_authority(self) -> None:
        plan = synthetic_plan(
            candidate_state=DATA_STALE,
            candidate_event_id="8" * 64,
            candidate_evidence="9" * 64,
        )
        decision = synthetic_decision(plan, authorized=False)
        forged = replace(
            decision,
            status=DECISION_AUTHORIZED,
            final_authorized_quantity="0.25",
            plan_status=READY_FOR_RISK_REVIEW,
            plan_blockers=(),
            risk_status=RISK_AUTHORIZED,
            allocation_status=ALLOCATION_AUTHORIZED,
            blockers=(),
            fingerprint="",
        )
        forged = replace(
            forged,
            fingerprint=evidence_fingerprint(decision_fingerprint_payload(forged)),
        )

        with self.assertRaisesRegex(EventDecisionCycleError, "plan authority"):
            self.process_cycle(
                plan=plan,
                decision=forged,
                trigger=synthetic_trigger(
                    plan,
                    trigger_type=CANDIDATE_STATE_CHANGED,
                    next_state=DATA_STALE,
                ),
            )
        self.assertFalse(self.path.exists())

    def test_cycle_start_cannot_precede_trigger_receipt(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan)
        trigger = synthetic_trigger(plan)
        with self.assertRaisesRegex(EventDecisionCycleError, "chronology"):
            self.coordinator.process(
                trigger,
                recorded_at=BASE + timedelta(seconds=3),
                cycle_started_at=datetime.fromisoformat(trigger.receipt_timestamp)
                - timedelta(seconds=1),
                plan_version=plan,
                decision=decision,
            )

    def test_plan_cannot_predate_trigger_receipt(self) -> None:
        plan = synthetic_plan()
        occurred = BASE + timedelta(seconds=5)
        trigger = synthetic_trigger(plan, occurred_at=occurred)
        with self.assertRaisesRegex(EventDecisionCycleError, "predates"):
            self.process_cycle(
                plan=plan,
                decision=synthetic_decision(plan, decided_at=BASE + timedelta(seconds=8)),
                trigger=trigger,
                recorded_at=BASE + timedelta(seconds=9),
            )

    def test_naive_trigger_timestamp_is_rejected(self) -> None:
        plan = synthetic_plan()
        with self.assertRaisesRegex(EventDecisionCycleError, "UTC offset"):
            build_decision_trigger(
                trigger_type=MEANINGFUL_LEVEL_BREAK,
                opportunity_id=plan.opportunity_id,
                setup_id=plan.setup_id,
                symbol=plan.symbol,
                session_date=plan.session_date,
                previous_candidate_state=WATCHING,
                next_candidate_state=plan.candidate_state,
                occurred_at=datetime(2026, 8, 10, 14, 0),
                provider_timestamp=BASE - timedelta(seconds=1),
                receipt_timestamp=BASE + timedelta(seconds=1),
                source_identity="synthetic",
                source_evidence_id="event-1",
                source_evidence_fingerprint=SETUP_EVIDENCE,
                material_delta_kind="LEVEL_BREAK",
                materiality=MATERIAL,
            )

    def test_policy_cannot_enable_quote_only_cycles(self) -> None:
        with self.assertRaisesRegex(EventDecisionCycleError, "Quote-only"):
            validate_policy(
                synthetic_policy(quote_only_events_create_cycles=True)
            )

    def test_policy_trigger_types_must_be_sorted_and_unique(self) -> None:
        cases = (
            (MEANINGFUL_LEVEL_BREAK, CANDIDATE_STATE_CHANGED),
            (CANDIDATE_STATE_CHANGED, CANDIDATE_STATE_CHANGED),
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaisesRegex(EventDecisionCycleError, "canonical"):
                    validate_policy(synthetic_policy(allowed_trigger_types=values))

    def test_persisted_trigger_tampering_is_detected(self) -> None:
        self.process_cycle()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["receipts"][0]["trigger"]["symbol"] = "BBB"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(EventDecisionCycleError, "fingerprint"):
            self.store.load()

    def test_persisted_cycle_tampering_is_detected(self) -> None:
        self.process_cycle()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["cycles"][0]["final_authorized_quantity"] = "99"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(EventDecisionCycleError, "fingerprint"):
            self.store.load()

    def test_orphaned_created_receipt_is_rejected(self) -> None:
        self.process_cycle()
        ledger = self.store.load()
        orphaned = replace(ledger, cycles=())
        with self.assertRaisesRegex(EventDecisionCycleError, "inconsistent"):
            validate_ledger(orphaned)

    def test_processing_receipt_cannot_predate_completed_decision(self) -> None:
        with self.assertRaisesRegex(EventDecisionCycleError, "completed decision"):
            self.process_cycle(recorded_at=BASE + timedelta(seconds=1))
        self.assertFalse(self.path.exists())

    def test_cycle_policy_binding_tampering_is_detected(self) -> None:
        self.process_cycle()
        ledger = self.store.load()
        cycle = replace(ledger.cycles[0], configuration_fingerprint="0" * 64)
        cycle = replace(cycle, fingerprint=cycle_fingerprint(replace(cycle, fingerprint="")))
        with self.assertRaisesRegex(EventDecisionCycleError, "policy"):
            validate_ledger(replace(ledger, cycles=(cycle,)))

    def test_cycle_source_binding_tampering_is_detected(self) -> None:
        self.process_cycle()
        ledger = self.store.load()
        cycle = replace(ledger.cycles[0], symbol="BBB")
        cycle = replace(cycle, fingerprint=cycle_fingerprint(replace(cycle, fingerprint="")))
        with self.assertRaisesRegex(EventDecisionCycleError, "source binding"):
            validate_ledger(replace(ledger, cycles=(cycle,)))

    def test_created_receipt_predecessor_tampering_is_detected(self) -> None:
        first = self.process_cycle()
        assert first.cycle is not None
        later_plan = synthetic_plan(created_at=BASE + timedelta(seconds=400))
        later_trigger = synthetic_trigger(
            later_plan,
            trigger_type=MEANINGFUL_LEVEL_BREAK,
            source_evidence_id="later-break",
        )
        self.process_cycle(
            plan=later_plan,
            decision=synthetic_decision(later_plan, nonce="later"),
            trigger=later_trigger,
        )
        ledger = self.store.load()
        receipt = replace(ledger.receipts[1], predecessor_cycle_id="", fingerprint="")
        receipt = replace(receipt, fingerprint=receipt_fingerprint(receipt))
        with self.assertRaisesRegex(EventDecisionCycleError, "predecessor binding"):
            validate_ledger(replace(ledger, receipts=(ledger.receipts[0], receipt)))

    def test_duplicate_created_cycle_receipt_is_detected(self) -> None:
        first = self.process_cycle()
        assert first.cycle is not None
        later_plan = synthetic_plan(created_at=BASE + timedelta(seconds=400))
        later_trigger = synthetic_trigger(
            later_plan,
            trigger_type=MEANINGFUL_LEVEL_BREAK,
            source_evidence_id="later-break",
        )
        self.process_cycle(
            plan=later_plan,
            decision=synthetic_decision(later_plan, nonce="later"),
            trigger=later_trigger,
        )
        ledger = self.store.load()
        receipt = replace(
            ledger.receipts[1], cycle_id=first.cycle.cycle_id, fingerprint=""
        )
        receipt = replace(receipt, fingerprint=receipt_fingerprint(receipt))
        with self.assertRaisesRegex(EventDecisionCycleError, "duplicated"):
            validate_ledger(replace(ledger, receipts=(ledger.receipts[0], receipt)))

    def test_atomic_replace_failure_preserves_previous_ledger(self) -> None:
        self.process_cycle()
        before = self.path.read_bytes()
        ledger = self.store.load()
        with patch(
            "momentum_hunter.event_driven_decision_cycle.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaises(OSError):
                self.store.save(ledger)
        self.assertEqual(before, self.path.read_bytes())

    def test_two_coordinators_do_not_lose_concurrent_appends(self) -> None:
        other_plan = synthetic_plan(
            opportunity_id="0" * 64,
            setup_id="a" * 64,
            intraday_plan_id="b" * 64,
            candidate_event_id="c" * 64,
            candidate_evidence="d" * 64,
        )
        work = (
            (synthetic_plan(), "first", EventDecisionCycleStore(self.path)),
            (other_plan, "second", EventDecisionCycleStore(self.path)),
        )

        def append(item) -> str:
            plan, nonce, store = item
            trigger = synthetic_trigger(
                plan, source_evidence_id=f"concurrent-{nonce}"
            )
            coordinator = EventDecisionCycleCoordinator(store, policy=self.policy)
            result = coordinator.process(
                trigger,
                recorded_at=BASE + timedelta(seconds=3),
                cycle_started_at=datetime.fromisoformat(trigger.receipt_timestamp)
                + timedelta(milliseconds=100),
                plan_version=plan,
                decision=synthetic_decision(plan, nonce=nonce),
            )
            return result.receipt.receipt_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            receipt_ids = tuple(executor.map(append, work))

        ledger = self.store.load()
        self.assertEqual(2, len(set(receipt_ids)))
        self.assertEqual(2, len(ledger.receipts))
        self.assertEqual(2, len(ledger.cycles))

    def test_input_records_are_not_mutated(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan)
        trigger = synthetic_trigger(plan)
        before = (
            asdict(plan),
            asdict(decision),
            asdict(trigger),
        )
        self.process_cycle(plan=plan, decision=decision, trigger=trigger)
        self.assertEqual(before, (asdict(plan), asdict(decision), asdict(trigger)))

    def test_independent_opportunities_do_not_share_cooldown(self) -> None:
        self.process_cycle()
        other_plan = synthetic_plan(
            opportunity_id="0" * 64,
            setup_id="a" * 64,
            intraday_plan_id="b" * 64,
            candidate_event_id="c" * 64,
            candidate_evidence="d" * 64,
        )
        other_trigger = synthetic_trigger(
            other_plan,
            source_evidence_id="other-opportunity",
        )
        result = self.process_cycle(
            plan=other_plan,
            decision=synthetic_decision(other_plan, nonce="other"),
            trigger=other_trigger,
        )
        assert result.cycle is not None
        self.assertEqual(1, result.cycle.sequence)
        self.assertEqual("", result.cycle.predecessor_cycle_id)

    def test_deterministic_inputs_produce_byte_identical_ledgers(self) -> None:
        plan = synthetic_plan()
        decision = synthetic_decision(plan)
        trigger = synthetic_trigger(plan)
        first_path = self.root / "first.json"
        second_path = self.root / "second.json"
        for path in (first_path, second_path):
            coordinator = EventDecisionCycleCoordinator(
                EventDecisionCycleStore(path), policy=self.policy
            )
            coordinator.process(
                trigger,
                recorded_at=BASE + timedelta(seconds=3),
                cycle_started_at=datetime.fromisoformat(trigger.receipt_timestamp)
                + timedelta(milliseconds=100),
                plan_version=plan,
                decision=decision,
            )
        self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_module_has_no_network_broker_or_runtime_capability(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "event_driven_decision_cycle.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
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
                    "shadow_selection",
                }
            )
        )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            calls.isdisjoint(
                {"submit_order", "cancel_order", "replace_order", "get_account"}
            )
        )

    def test_no_existing_runtime_imports_event_cycle_module(self) -> None:
        root = Path(__file__).resolve().parents[1]
        importers = []
        for path in (root / "momentum_hunter").rglob("*.py"):
            if path.name == "event_driven_decision_cycle.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "event_driven_decision_cycle" in text:
                importers.append(str(path.relative_to(root)))
        self.assertEqual([], importers)


if __name__ == "__main__":
    unittest.main()
