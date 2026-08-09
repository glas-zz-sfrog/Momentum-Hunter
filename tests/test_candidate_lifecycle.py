from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from momentum_hunter.candidate_lifecycle import (
    AVAILABILITY_FAILED,
    AVAILABILITY_MISSED,
    AVAILABILITY_RECOVERED,
    BREAKOUT_CONFIRMED,
    BREAKOUT_FORMING,
    COOLDOWN,
    COOLDOWN_BOUNDARY,
    CREATED,
    DATA_BECAME_STALE,
    DATA_STALE,
    DISCOVERED,
    DISCOVERY_MEMBERSHIP_CHANGED,
    DISCOVERY_SCOPE,
    DUPLICATE,
    ENTRY_MISSED,
    EVIDENCE_AUTHORITY_CHANGED,
    EVIDENCE_REFRESH_EVENT,
    EXECUTION_ELIGIBLE,
    FAILED_BREAKOUT,
    IMPULSE_DETECTED,
    INVALIDATED,
    INVALIDATION_BOUNDARY,
    MONITORING_ACTIVATED,
    MONITORING_SCOPE,
    NO_CHANGE,
    PULLBACK_FORMING,
    RECLAIM_FORMING,
    SETUP_IDENTITY_CHANGED,
    SETUP_STATE_CHANGED,
    WATCHING,
    CandidateLifecycleCoordinator,
    CandidateLifecycleError,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
    availability_event_fingerprint,
    expected_candidate_event_id,
    expected_opportunity_id,
    expected_setup_id,
    ledger_to_wire,
    lifecycle_event_fingerprint,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    PULLBACK,
    RECLAIM,
)


BASE = datetime.fromisoformat("2026-08-10T09:35:00-04:00")


class CandidateLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "candidate-lifecycle.json"
        self.store = CandidateLifecycleStore(self.path)
        self.policy = lifecycle_policy()
        self.coordinator = CandidateLifecycleCoordinator(
            self.store, policy=self.policy
        )
        self.opportunity_id = ""

    def discover(self, *, evidence: str = "a" * 64, minute: int = 0):
        result = self.coordinator.discover(
            symbol="abc",
            session_date="2026-08-10",
            originating_evidence_family="OPENING_BOOTSTRAP",
            evidence_fingerprint=evidence,
            source_identity="synthetic-opening-capture",
            occurred_at=at(minute),
            provider_timestamp=at(minute) - timedelta(seconds=1),
            receipt_timestamp=at(minute),
            reason="Candidate appeared in the bounded opening bootstrap.",
        )
        self.opportunity_id = result.snapshot.opportunity_id
        return result

    def transition(
        self,
        state: str,
        *,
        evidence: str,
        minute: int,
        delta: str = SETUP_STATE_CHANGED,
        setup_family: str = "",
        create_new_setup: bool = False,
        reason: str | None = None,
    ):
        return self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state=state,
            evidence_fingerprint=evidence,
            source_identity="synthetic-canonical-candles",
            occurred_at=at(minute),
            provider_timestamp=at(minute) - timedelta(seconds=1),
            receipt_timestamp=at(minute),
            reason=reason or f"Synthetic transition to {state}.",
            material_delta_kind=delta,
            setup_family=setup_family,
            create_new_setup=create_new_setup,
        )

    def test_discovery_creates_stable_opportunity_and_persists(self) -> None:
        result = self.discover()

        self.assertEqual(CREATED, result.status)
        self.assertEqual(DISCOVERED, result.snapshot.current_state)
        self.assertEqual(
            expected_opportunity_id(
                "ABC", "2026-08-10", "OPENING_BOOTSTRAP"
            ),
            result.snapshot.opportunity_id,
        )
        reloaded = CandidateLifecycleCoordinator(
            CandidateLifecycleStore(self.path), policy=self.policy
        ).snapshot(result.snapshot.opportunity_id)
        self.assertEqual(result.snapshot, reloaded)

    def test_exact_discovery_replay_is_idempotent_and_byte_identical(self) -> None:
        first = self.discover()
        before = self.path.read_bytes()

        repeated = self.discover()

        self.assertEqual(DUPLICATE, repeated.status)
        self.assertEqual(first.event, repeated.event)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(self.store.load().events))

    def test_discovery_refresh_preserves_existing_watch_state(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )

        refreshed = self.discover(evidence="c" * 64, minute=2)

        self.assertEqual(CREATED, refreshed.status)
        self.assertEqual(EVIDENCE_REFRESH_EVENT, refreshed.event.event_type)
        self.assertEqual(WATCHING, refreshed.event.previous_state)
        self.assertEqual(WATCHING, refreshed.snapshot.current_state)
        self.assertEqual("c" * 64, refreshed.snapshot.latest_evidence_fingerprint)

    def test_historical_discovery_replay_is_no_change_after_progression(self) -> None:
        first = self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        before = self.path.read_bytes()

        replayed = self.discover()

        self.assertEqual(NO_CHANGE, replayed.status)
        self.assertIsNone(replayed.event)
        self.assertEqual(WATCHING, replayed.snapshot.current_state)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(first.event.event_id, self.store.load().events[0].event_id)

    def test_same_evidence_and_state_is_explicit_no_change(self) -> None:
        self.discover()

        result = self.transition(
            DISCOVERED,
            evidence="a" * 64,
            minute=1,
            delta=EVIDENCE_AUTHORITY_CHANGED,
        )

        self.assertEqual(NO_CHANGE, result.status)
        self.assertIsNone(result.event)
        self.assertEqual(1, len(self.store.load().events))

    def test_identical_evidence_cannot_produce_conflicting_state(self) -> None:
        self.discover()

        with self.assertRaisesRegex(
            CandidateLifecycleError, "Identical candidate evidence"
        ):
            self.transition(WATCHING, evidence="a" * 64, minute=1)

    def test_watch_and_breakout_progression_preserves_one_setup_identity(self) -> None:
        self.discover()
        watched = self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        impulse = self.transition(
            IMPULSE_DETECTED, evidence="c" * 64, minute=2
        )
        forming = self.transition(
            BREAKOUT_FORMING,
            evidence="d" * 64,
            minute=3,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
        )
        confirmed = self.transition(
            BREAKOUT_CONFIRMED, evidence="e" * 64, minute=4
        )

        self.assertEqual(WATCHING, watched.snapshot.current_state)
        self.assertEqual(IMPULSE_DETECTED, impulse.snapshot.current_state)
        self.assertEqual(
            expected_setup_id(
                self.opportunity_id, CONTINUATION_BREAKOUT, 1
            ),
            forming.snapshot.current_setup_id,
        )
        self.assertEqual(
            forming.snapshot.current_setup_id, confirmed.snapshot.current_setup_id
        )
        self.assertEqual(1, confirmed.snapshot.current_setup_sequence)

    def test_setup_bound_state_requires_setup_family(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )

        with self.assertRaisesRegex(CandidateLifecycleError, "setup family"):
            self.transition(BREAKOUT_FORMING, evidence="c" * 64, minute=2)

    def test_setup_family_must_match_setup_specific_state(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )

        with self.assertRaisesRegex(CandidateLifecycleError, "Breakout lifecycle"):
            self.transition(
                BREAKOUT_FORMING,
                evidence="c" * 64,
                minute=2,
                setup_family=PULLBACK,
            )
        with self.assertRaisesRegex(CandidateLifecycleError, "PULLBACK_FORMING"):
            self.transition(
                PULLBACK_FORMING,
                evidence="d" * 64,
                minute=2,
                setup_family=CONTINUATION_BREAKOUT,
            )
        with self.assertRaisesRegex(CandidateLifecycleError, "RECLAIM_FORMING"):
            self.transition(
                RECLAIM_FORMING,
                evidence="e" * 64,
                minute=2,
                setup_family=PULLBACK,
            )
        self.assertEqual(
            WATCHING, self.coordinator.snapshot(self.opportunity_id).current_state
        )

    def test_missed_breakout_becomes_distinct_pullback_setup(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        breakout = self.transition(
            BREAKOUT_FORMING,
            evidence="c" * 64,
            minute=2,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
        )
        missed = self.transition(ENTRY_MISSED, evidence="d" * 64, minute=3)
        pullback = self.transition(
            PULLBACK_FORMING,
            evidence="e" * 64,
            minute=4,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=PULLBACK,
        )

        self.assertEqual(
            breakout.snapshot.current_setup_id, missed.snapshot.current_setup_id
        )
        self.assertNotEqual(
            missed.snapshot.current_setup_id, pullback.snapshot.current_setup_id
        )
        self.assertEqual(2, pullback.snapshot.current_setup_sequence)
        self.assertEqual(
            missed.snapshot.current_setup_id,
            pullback.event.predecessor_setup_id,
        )

    def test_same_family_can_create_new_setup_after_cooldown(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        first = self.transition(
            BREAKOUT_FORMING,
            evidence="c" * 64,
            minute=2,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
        )
        self.transition(ENTRY_MISSED, evidence="d" * 64, minute=3)
        self.transition(
            COOLDOWN,
            evidence="e" * 64,
            minute=4,
            delta=COOLDOWN_BOUNDARY,
        )
        self.transition(
            WATCHING,
            evidence="f" * 64,
            minute=5,
            delta=COOLDOWN_BOUNDARY,
        )
        second = self.transition(
            BREAKOUT_FORMING,
            evidence="1" * 64,
            minute=6,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
            create_new_setup=True,
        )

        self.assertNotEqual(
            first.snapshot.current_setup_id, second.snapshot.current_setup_id
        )
        self.assertEqual(2, second.snapshot.current_setup_sequence)
        self.assertEqual(
            first.snapshot.current_setup_id, second.event.predecessor_setup_id
        )

    def test_cooldown_expiry_is_enforced_by_versioned_policy(self) -> None:
        self.discover()
        self.transition(
            INVALIDATED,
            evidence="b" * 64,
            minute=1,
            delta=INVALIDATION_BOUNDARY,
        )
        self.transition(
            COOLDOWN,
            evidence="c" * 64,
            minute=2,
            delta=COOLDOWN_BOUNDARY,
        )
        replacement_policy = CandidateLifecyclePolicy(
            policy_version="synthetic-policy-v2",
            cooldown_seconds=0,
            hysteresis_profile="STRUCTURAL_TRANSITIONS_ONLY",
            minimum_delta_profile="MATERIAL_EVENT_ALLOWLIST_V1",
            quote_only_events_create_cycles=False,
        )
        replacement = CandidateLifecycleCoordinator(
            self.store, policy=replacement_policy
        )

        with self.assertRaisesRegex(CandidateLifecycleError, "cooldown"):
            replacement.transition(
                opportunity_id=self.opportunity_id,
                next_state=WATCHING,
                evidence_fingerprint="d" * 64,
                source_identity="synthetic-canonical-candles",
                occurred_at=at(2) + timedelta(seconds=59),
                provider_timestamp=at(2) + timedelta(seconds=58),
                receipt_timestamp=at(2) + timedelta(seconds=59),
                reason="Cooldown has not finished.",
                material_delta_kind=COOLDOWN_BOUNDARY,
            )

        resumed = replacement.transition(
            opportunity_id=self.opportunity_id,
            next_state=WATCHING,
            evidence_fingerprint="e" * 64,
            source_identity="synthetic-canonical-candles",
            occurred_at=at(3),
            provider_timestamp=at(3) - timedelta(seconds=1),
            receipt_timestamp=at(3),
            reason="Persisted cooldown has finished.",
            material_delta_kind=COOLDOWN_BOUNDARY,
        )
        self.assertEqual(WATCHING, resumed.snapshot.current_state)
        self.assertEqual(
            replacement_policy.fingerprint, resumed.event.policy_fingerprint
        )

    def test_generic_transition_cannot_bypass_explicit_stale_path(self) -> None:
        self.discover()

        with self.assertRaisesRegex(CandidateLifecycleError, "mark_stale"):
            self.transition(
                DATA_STALE,
                evidence="b" * 64,
                minute=1,
                delta=DATA_BECAME_STALE,
            )

    def test_quote_only_cycle_policy_is_structurally_rejected(self) -> None:
        with self.assertRaisesRegex(CandidateLifecycleError, "Quote-only"):
            CandidateLifecycleCoordinator(
                self.store,
                policy=CandidateLifecyclePolicy(
                    policy_version="synthetic-policy-v1",
                    cooldown_seconds=60,
                    hysteresis_profile="STRUCTURAL_TRANSITIONS_ONLY",
                    minimum_delta_profile="MATERIAL_EVENT_ALLOWLIST_V1",
                    quote_only_events_create_cycles=True,
                ),
            )

    def test_failed_breakout_reclaim_is_separate_setup(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        breakout = self.transition(
            BREAKOUT_FORMING,
            evidence="c" * 64,
            minute=2,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
        )
        self.transition(FAILED_BREAKOUT, evidence="d" * 64, minute=3)
        reclaim = self.transition(
            RECLAIM_FORMING,
            evidence="e" * 64,
            minute=4,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=RECLAIM,
        )

        self.assertNotEqual(
            breakout.snapshot.current_setup_id, reclaim.snapshot.current_setup_id
        )
        self.assertEqual(RECLAIM, reclaim.snapshot.current_setup_family)
        self.assertEqual(2, reclaim.snapshot.current_setup_sequence)

    def test_illegal_transition_fails_closed_without_mutation(self) -> None:
        self.discover()
        before = self.path.read_bytes()

        with self.assertRaisesRegex(CandidateLifecycleError, "Illegal"):
            self.transition(EXECUTION_ELIGIBLE, evidence="b" * 64, minute=1)

        self.assertEqual(before, self.path.read_bytes())

    def test_new_evidence_can_be_recorded_without_state_change(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )

        refreshed = self.transition(
            WATCHING,
            evidence="c" * 64,
            minute=2,
            delta=EVIDENCE_AUTHORITY_CHANGED,
        )

        self.assertEqual(CREATED, refreshed.status)
        self.assertEqual("EVIDENCE_REFRESH", refreshed.event.event_type)
        self.assertEqual(WATCHING, refreshed.event.previous_state)
        self.assertEqual(WATCHING, refreshed.event.next_state)

    def test_stale_recovery_returns_to_last_noneligible_state(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        stale = self.coordinator.mark_stale(
            opportunity_id=self.opportunity_id,
            evidence_fingerprint="c" * 64,
            source_identity="synthetic-stream-health",
            occurred_at=at(2),
            provider_timestamp=at(2) - timedelta(seconds=1),
            receipt_timestamp=at(2),
            reason="Required candle continuity became stale.",
        )
        recovered = self.coordinator.recover(
            opportunity_id=self.opportunity_id,
            evidence_fingerprint="d" * 64,
            source_identity="synthetic-gap-reconciliation",
            occurred_at=at(3),
            provider_timestamp=at(3) - timedelta(seconds=1),
            receipt_timestamp=at(3),
            reason="Required evidence was revalidated and the gap was disposed.",
        )

        self.assertEqual(DATA_STALE, stale.snapshot.current_state)
        self.assertEqual(WATCHING, stale.snapshot.last_non_stale_state)
        self.assertEqual(WATCHING, recovered.snapshot.current_state)
        self.assertEqual("DATA_RECOVERED", recovered.event.event_type)

    def test_stale_after_eligible_recovers_only_to_prior_noneligible_state(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        self.transition(
            BREAKOUT_FORMING,
            evidence="c" * 64,
            minute=2,
            delta=SETUP_IDENTITY_CHANGED,
            setup_family=CONTINUATION_BREAKOUT,
        )
        self.transition(BREAKOUT_CONFIRMED, evidence="d" * 64, minute=3)
        self.transition(EXECUTION_ELIGIBLE, evidence="e" * 64, minute=4)
        self.coordinator.mark_stale(
            opportunity_id=self.opportunity_id,
            evidence_fingerprint="f" * 64,
            source_identity="synthetic-stream-health",
            occurred_at=at(5),
            provider_timestamp=at(5) - timedelta(seconds=1),
            receipt_timestamp=at(5),
            reason="Quote authority became stale.",
        )

        recovered = self.coordinator.recover(
            opportunity_id=self.opportunity_id,
            evidence_fingerprint="1" * 64,
            source_identity="synthetic-authority-recheck",
            occurred_at=at(6),
            provider_timestamp=at(6) - timedelta(seconds=1),
            receipt_timestamp=at(6),
            reason="Authority inputs recovered without reusing eligibility.",
        )

        self.assertEqual(BREAKOUT_CONFIRMED, recovered.snapshot.current_state)
        self.assertNotEqual(EXECUTION_ELIGIBLE, recovered.snapshot.current_state)

    def test_stale_state_blocks_normal_promotion(self) -> None:
        self.discover()
        self.coordinator.mark_stale(
            opportunity_id=self.opportunity_id,
            evidence_fingerprint="b" * 64,
            source_identity="synthetic-stream-health",
            occurred_at=at(1),
            provider_timestamp=at(1) - timedelta(seconds=1),
            receipt_timestamp=at(1),
            reason="Required evidence is missing.",
        )

        with self.assertRaisesRegex(CandidateLifecycleError, "Illegal"):
            self.transition(WATCHING, evidence="c" * 64, minute=2)

    def test_availability_failure_does_not_erase_or_mutate_watch_state(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        before = self.coordinator.snapshot(self.opportunity_id)

        failure = self.coordinator.record_availability(
            scope=DISCOVERY_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=at(2),
            source_identity="synthetic-discovery-run",
            evidence_fingerprint="c" * 64,
            reason="The bounded discovery run failed.",
        )
        repeated = self.coordinator.record_availability(
            scope=DISCOVERY_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=at(2),
            source_identity="synthetic-discovery-run",
            evidence_fingerprint="c" * 64,
            reason="The bounded discovery run failed.",
        )

        self.assertEqual(failure, repeated)
        self.assertEqual(before, self.coordinator.snapshot(self.opportunity_id))
        self.assertEqual(1, len(self.store.load().availability_events))

    def test_monitor_miss_and_recovery_are_preserved_without_backfill(self) -> None:
        self.discover()
        missed = self.coordinator.record_availability(
            scope=MONITORING_SCOPE,
            status=AVAILABILITY_MISSED,
            occurred_at=at(10),
            source_identity="synthetic-monitor-cycle",
            evidence_fingerprint="b" * 64,
            reason="Expected monitor cycle has no runtime evidence.",
        )
        recovered = self.coordinator.record_availability(
            scope=MONITORING_SCOPE,
            status=AVAILABILITY_RECOVERED,
            occurred_at=at(15),
            source_identity="synthetic-monitor-cycle",
            evidence_fingerprint="c" * 64,
            reason="Monitoring resumed prospectively.",
        )

        self.assertEqual(AVAILABILITY_MISSED, missed.status)
        self.assertEqual(AVAILABILITY_RECOVERED, recovered.status)
        self.assertEqual([1, 2], [event.sequence for event in (missed, recovered)])
        self.assertEqual(1, len(self.store.load().events))

    def test_availability_recovery_and_chronology_fail_closed(self) -> None:
        with self.assertRaisesRegex(CandidateLifecycleError, "prior failure or missed"):
            self.coordinator.record_availability(
                scope=MONITORING_SCOPE,
                status=AVAILABILITY_RECOVERED,
                occurred_at=at(2),
                source_identity="synthetic-monitor-cycle",
                evidence_fingerprint="b" * 64,
                reason="Recovery without a persisted outage.",
            )
        self.coordinator.record_availability(
            scope=MONITORING_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=at(5),
            source_identity="synthetic-monitor-cycle",
            evidence_fingerprint="c" * 64,
            reason="Monitoring failed.",
        )
        with self.assertRaisesRegex(CandidateLifecycleError, "predates"):
            self.coordinator.record_availability(
                scope=MONITORING_SCOPE,
                status=AVAILABILITY_MISSED,
                occurred_at=at(4),
                source_identity="synthetic-monitor-cycle",
                evidence_fingerprint="d" * 64,
                reason="A late record cannot rewrite chronology.",
            )

    def test_out_of_order_transition_is_rejected(self) -> None:
        self.discover(minute=5)

        with self.assertRaisesRegex(CandidateLifecycleError, "predates"):
            self.transition(
                WATCHING,
                evidence="b" * 64,
                minute=4,
                delta=MONITORING_ACTIVATED,
            )

    def test_invalidated_setup_is_preserved_then_may_enter_cooldown(self) -> None:
        self.discover()
        invalidated = self.transition(
            INVALIDATED,
            evidence="b" * 64,
            minute=1,
            delta=INVALIDATION_BOUNDARY,
        )
        cooldown = self.transition(
            COOLDOWN,
            evidence="c" * 64,
            minute=2,
            delta=COOLDOWN_BOUNDARY,
        )

        self.assertEqual(INVALIDATED, invalidated.event.next_state)
        self.assertEqual(INVALIDATED, cooldown.event.previous_state)
        self.assertEqual(COOLDOWN, cooldown.snapshot.current_state)

    def test_different_session_or_origin_family_creates_distinct_opportunity(self) -> None:
        first = self.discover()
        next_session = self.coordinator.discover(
            symbol="ABC",
            session_date="2026-08-11",
            originating_evidence_family="OPENING_BOOTSTRAP",
            evidence_fingerprint="b" * 64,
            source_identity="synthetic-opening-capture",
            occurred_at=at(1) + timedelta(days=1),
            provider_timestamp=at(1) + timedelta(days=1, seconds=-1),
            receipt_timestamp=at(1) + timedelta(days=1),
            reason="Candidate appeared in the next session.",
        )
        catalyst = self.coordinator.discover(
            symbol="ABC",
            session_date="2026-08-10",
            originating_evidence_family="CATALYST_DISCOVERY",
            evidence_fingerprint="c" * 64,
            source_identity="synthetic-catalyst-source",
            occurred_at=at(2),
            provider_timestamp=at(2) - timedelta(seconds=1),
            receipt_timestamp=at(2),
            reason="Candidate appeared through a distinct evidence family.",
        )

        self.assertEqual(
            3,
            len(
                {
                    first.snapshot.opportunity_id,
                    next_session.snapshot.opportunity_id,
                    catalyst.snapshot.opportunity_id,
                }
            ),
        )

    def test_conflicting_replay_reason_fails_closed(self) -> None:
        self.discover()

        with self.assertRaisesRegex(CandidateLifecycleError, "replay conflicts"):
            self.coordinator.discover(
                symbol="ABC",
                session_date="2026-08-10",
                originating_evidence_family="OPENING_BOOTSTRAP",
                evidence_fingerprint="a" * 64,
                source_identity="synthetic-opening-capture",
                occurred_at=at(0),
                provider_timestamp=at(0) - timedelta(seconds=1),
                receipt_timestamp=at(0),
                reason="A contradictory replay reason.",
            )

    def test_tampered_event_fingerprint_fails_load(self) -> None:
        self.discover()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["events"][0]["reason"] = "Tampered reason"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "fingerprint"):
            self.store.load()

    def test_tampered_previous_state_chain_fails_even_with_rehashed_record(self) -> None:
        self.discover()
        self.transition(
            WATCHING,
            evidence="b" * 64,
            minute=1,
            delta=MONITORING_ACTIVATED,
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        event_payload = payload["events"][1]
        event_payload["previous_state"] = IMPULSE_DETECTED
        event = type(self.store.load().events[1])(**event_payload)
        event = replace(event, fingerprint=lifecycle_event_fingerprint(event))
        payload["events"][1] = asdict(event)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "previous state"):
            self.store.load()

    def test_tampered_availability_fingerprint_fails_load(self) -> None:
        self.coordinator.record_availability(
            scope=MONITORING_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=at(1),
            source_identity="synthetic-monitor-cycle",
            evidence_fingerprint="b" * 64,
            reason="Monitoring failed.",
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["availability_events"][0]["reason"] = "Tampered"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "fingerprint"):
            self.store.load()

    def test_rehashed_policy_tampering_fails_independent_validation(self) -> None:
        self.discover()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        event_payload = payload["events"][0]
        event_payload["cooldown_seconds"] = 999
        event = type(self.store.load().events[0])(**event_payload)
        event = replace(event, fingerprint=lifecycle_event_fingerprint(event))
        payload["events"][0] = asdict(event)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "policy fingerprint"):
            self.store.load()

    def test_rehashed_availability_policy_tampering_fails_validation(self) -> None:
        recorded = self.coordinator.record_availability(
            scope=DISCOVERY_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=at(1),
            source_identity="synthetic-discovery-cycle",
            evidence_fingerprint="b" * 64,
            reason="Discovery failed.",
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        event_payload = payload["availability_events"][0]
        event_payload["minimum_delta_profile"] = "TAMPERED"
        event = type(recorded)(**event_payload)
        event = replace(event, fingerprint=availability_event_fingerprint(event))
        payload["availability_events"][0] = asdict(event)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "policy fingerprint"):
            self.store.load()

    def test_rehashed_arbitrary_event_identity_fails_validation(self) -> None:
        self.discover()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        event_payload = payload["events"][0]
        event_payload["event_id"] = "f" * 64
        event = type(self.store.load().events[0])(**event_payload)
        event = replace(event, fingerprint=lifecycle_event_fingerprint(event))
        payload["events"][0] = asdict(event)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "event identity"):
            self.store.load()

    def test_replay_enforces_cooldown_policy_from_predecessor_event(self) -> None:
        self.discover()
        self.transition(
            INVALIDATED,
            evidence="b" * 64,
            minute=1,
            delta=INVALIDATION_BOUNDARY,
        )
        self.transition(
            COOLDOWN,
            evidence="c" * 64,
            minute=2,
            delta=COOLDOWN_BOUNDARY,
        )
        self.transition(
            WATCHING,
            evidence="d" * 64,
            minute=3,
            delta=COOLDOWN_BOUNDARY,
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        event_payload = payload["events"][-1]
        event_payload["occurred_at"] = (at(2) + timedelta(seconds=30)).isoformat()
        event_payload["provider_timestamp"] = (
            at(2) + timedelta(seconds=29)
        ).isoformat()
        event_payload["receipt_timestamp"] = (
            at(2) + timedelta(seconds=30)
        ).isoformat()
        event_payload["event_id"] = expected_candidate_event_id(
            opportunity_id=event_payload["opportunity_id"],
            next_state=event_payload["next_state"],
            evidence_fingerprint=event_payload["evidence_fingerprint"],
            occurred_at=event_payload["occurred_at"],
            source_identity=event_payload["source_identity"],
            material_delta_kind=event_payload["material_delta_kind"],
            event_type=event_payload["event_type"],
            provider_timestamp=event_payload["provider_timestamp"],
            receipt_timestamp=event_payload["receipt_timestamp"],
            policy_fingerprint=event_payload["policy_fingerprint"],
            setup_id=event_payload["setup_id"],
            previous_event_id=event_payload["previous_event_id"],
        )
        event = type(self.store.load().events[-1])(**event_payload)
        event = replace(event, fingerprint=lifecycle_event_fingerprint(event))
        payload["events"][-1] = asdict(event)
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "persisted policy"):
            self.store.load()

    def test_atomic_replace_failure_preserves_prior_ledger(self) -> None:
        self.discover()
        before = self.path.read_bytes()

        with mock.patch(
            "momentum_hunter.candidate_lifecycle.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                self.transition(
                    WATCHING,
                    evidence="b" * 64,
                    minute=1,
                    delta=MONITORING_ACTIVATED,
                )

        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.path.parent.glob(f".{self.path.name}.*.tmp")))

    def test_offset_naive_clock_and_malformed_hash_fail_before_write(self) -> None:
        with self.assertRaisesRegex(CandidateLifecycleError, "UTC offset"):
            self.coordinator.discover(
                symbol="ABC",
                session_date="2026-08-10",
                originating_evidence_family="OPENING_BOOTSTRAP",
                evidence_fingerprint="a" * 64,
                source_identity="synthetic-opening-capture",
                occurred_at=datetime(2026, 8, 10, 9, 35),
                provider_timestamp=at(0),
                receipt_timestamp=at(0),
                reason="Candidate appeared.",
            )
        with self.assertRaisesRegex(CandidateLifecycleError, "fingerprint"):
            self.coordinator.discover(
                symbol="ABC",
                session_date="2026-08-10",
                originating_evidence_family="OPENING_BOOTSTRAP",
                evidence_fingerprint="not-a-hash",
                source_identity="synthetic-opening-capture",
                occurred_at=at(0),
                provider_timestamp=at(0),
                receipt_timestamp=at(0),
                reason="Candidate appeared.",
            )
        self.assertFalse(self.path.exists())

    def test_session_date_mismatch_and_malformed_ledger_rows_fail_closed(self) -> None:
        with self.assertRaisesRegex(CandidateLifecycleError, "market session date"):
            self.coordinator.discover(
                symbol="ABC",
                session_date="2026-08-11",
                originating_evidence_family="OPENING_BOOTSTRAP",
                evidence_fingerprint="a" * 64,
                source_identity="synthetic-opening-capture",
                occurred_at=at(0),
                provider_timestamp=at(0) - timedelta(seconds=1),
                receipt_timestamp=at(0),
                reason="Timestamp belongs to the prior market session.",
            )
        self.discover()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["events"][0] = "not-a-record"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CandidateLifecycleError, "malformed record"):
            self.store.load()

    def test_module_has_no_network_broker_scoring_or_selection_imports(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "candidate_lifecycle.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )

        forbidden = {
            "requests",
            "urllib",
            "http",
            "socket",
            "momentum_hunter.scoring",
            "momentum_hunter.shadow_selection",
            "momentum_hunter.autonomy",
            "momentum_hunter.execution",
            "momentum_hunter.alpaca_paper",
        }
        self.assertTrue(forbidden.isdisjoint(imports), imports & forbidden)


def at(minute: int) -> datetime:
    return BASE + timedelta(minutes=minute)


def lifecycle_policy() -> CandidateLifecyclePolicy:
    return CandidateLifecyclePolicy(
        policy_version="synthetic-policy-v1",
        cooldown_seconds=60,
        hysteresis_profile="STRUCTURAL_TRANSITIONS_ONLY",
        minimum_delta_profile="MATERIAL_EVENT_ALLOWLIST_V1",
        quote_only_events_create_cycles=False,
    )


if __name__ == "__main__":
    unittest.main()
