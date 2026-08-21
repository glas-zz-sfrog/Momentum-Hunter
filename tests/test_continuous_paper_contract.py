from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime

from momentum_hunter.continuous_composition import (
    ContinuousCompositionCycle,
    ContinuousCompositionMemberResult,
    ContinuousCompositionSummary,
    ContinuousReadinessAssessment,
    LifecycleTransitionProposal,
)
from momentum_hunter.continuous_paper_contract import (
    ContinuousPaperContractError,
    build_continuous_paper_admission_intent,
    parse_continuous_paper_admission_intent,
)
from momentum_hunter.hot_universe import HOT, TRACKED, HotUniverseMember
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.schwab_candle_contract import EASTERN_TZ


SESSION = "2026-08-20"


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 20, hour, minute, tzinfo=EASTERN_TZ)


def fixtures():
    plan = build_intraday_plan_evidence(
        symbol="SPCX",
        setup_family=CONTINUATION_BREAKOUT,
        created_at=at(11, 0),
        planned_entry=100.0,
        stop_price=98.0,
        target_prices=(104.0,),
        source_setup_fingerprint="e" * 64,
        source_level_kind="TEST_ONLY_STRUCTURE",
        source_evidence_ids=("minute:SPCX:2026-08-20T10:59:00-04:00",),
    )
    assessment = ContinuousReadinessAssessment(
        universe_member_id="member-spcx",
        symbol="SPCX",
        session_date=SESSION,
        evaluated_at=at(11, 0).isoformat(),
        minute_evidence_id="minute-spcx",
        minute_evidence_fingerprint="1" * 64,
        daily_evidence_id="daily-spcx",
        daily_evidence_fingerprint="2" * 64,
        rvol_evidence_id="rvol-spcx",
        rvol_evidence_fingerprint="3" * 64,
        latest_completed_minute=at(10, 59).isoformat(),
        candle_canonicality="CANONICAL",
        history_depth_sessions=7,
        baseline_sufficiency="SUFFICIENT",
        gap_state="COMPLETE",
        stale_state="FRESH",
        status="READY",
        blocker_reasons=(),
        policy_fingerprint="4" * 64,
        fingerprint="5" * 64,
    )
    proposal = LifecycleTransitionProposal(
        opportunity_id="6" * 64,
        symbol="SPCX",
        session_date=SESSION,
        previous_state="WATCHING",
        next_state="BREAKOUT_FORMING",
        setup_id="e" * 64,
        setup_family=CONTINUATION_BREAKOUT,
        setup_sequence=1,
        predecessor_setup_id="",
        create_new_setup=True,
        occurred_at=at(11, 0).isoformat(),
        provider_timestamp=at(10, 59).isoformat(),
        receipt_timestamp=at(11, 0).isoformat(),
        source_identity="TEST_ONLY_STRUCTURE",
        evidence_fingerprint="7" * 64,
        material_delta_kind="SETUP_IDENTITY_CHANGED",
        reason="TEST_ONLY",
        fingerprint="8" * 64,
    )
    member_result = ContinuousCompositionMemberResult(
        universe_member_id="member-spcx",
        symbol="SPCX",
        session_date=SESSION,
        disposition="RESEARCH_PLAN_COMPOSED",
        readiness_request=None,
        readiness_assessment=assessment,
        lifecycle_proposal=proposal,
        intraday_plan=plan,
        blocker_reasons=(),
        authority="EXECUTION_AUTHORITY_NONE",
        fingerprint="9" * 64,
    )
    summary = ContinuousCompositionSummary(
        members_presented=1,
        readiness_requests=1,
        ready=1,
        waiting_readiness=0,
        insufficient_history=0,
        insufficient_rvol=0,
        provider_bound=0,
        data_failures=0,
        no_lifecycle_change=0,
        lifecycle_transitions=1,
        missed_entries=0,
        successor_setups=1,
        plans_composed=1,
    )
    cycle = ContinuousCompositionCycle(
        cycle_id="cycle-spcx",
        session_date=SESSION,
        started_at=at(10, 59).isoformat(),
        evidence_cutoff=at(11, 0).isoformat(),
        universe_policy_fingerprint="a" * 64,
        composition_policy_fingerprint="b" * 64,
        member_results=(member_result,),
        summary=summary,
        shared_failure_state="NONE",
        fingerprint="c" * 64,
    )
    universe_member = HotUniverseMember(
        member_id="member-spcx",
        symbol="SPCX",
        session_date=SESSION,
        membership_generation=1,
        first_observed_at=at(10, 30).isoformat(),
        last_observed_at=at(11, 0).isoformat(),
        first_discovery_snapshot_id="snapshot-1",
        latest_discovery_snapshot_id="snapshot-2",
        first_candidate_identity="candidate-spcx",
        latest_candidate_identity="candidate-spcx",
        latest_source_row_id="row-spcx",
        admission_reason="QUALIFIED",
        current_tier=HOT,
        current_state=TRACKED,
        source_observation_count=2,
        consecutive_absent_observations=0,
        consecutive_rejected_observations=0,
        last_qualified_at=at(11, 0).isoformat(),
        last_rejected_at="",
        last_source_seen_at=at(11, 0).isoformat(),
        active_setup_ids=(proposal.setup_id,),
        terminal_setup_count=0,
        protected_reason="",
        priority_inputs=(("canonicalRank", "1"),),
        capacity_disposition="ADMITTED",
        provider_bound_since="",
        provider_bound_observation_count=0,
        expires_at=at(15, 55).isoformat(),
        predecessor_fingerprint="d" * 64,
    )
    return cycle, member_result, universe_member


class ContinuousPaperContractTests(unittest.TestCase):
    def test_round_trip_is_deterministic_and_broker_blind(self):
        cycle, member_result, universe_member = fixtures()

        intent = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint="f" * 64,
            product_sha="1" * 40,
        )

        self.assertIsNotNone(intent)
        parsed = parse_continuous_paper_admission_intent(intent.to_dict())
        self.assertEqual(intent, parsed)
        self.assertEqual("RESEARCH_ONLY", parsed.authority)
        self.assertEqual("EXECUTION_AUTHORITY_NONE", parsed.execution_authority)
        self.assertEqual("UNAVAILABLE", parsed.order_capability)

    def test_tamper_is_rejected(self):
        cycle, member_result, universe_member = fixtures()
        intent = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint="f" * 64,
            product_sha="1" * 40,
        )
        payload = intent.to_dict()
        payload["symbol"] = "WRONG"

        with self.assertRaises(ContinuousPaperContractError):
            parse_continuous_paper_admission_intent(payload)

    def test_same_trade_plan_in_later_cycle_keeps_one_admission_identity(self):
        cycle, member_result, universe_member = fixtures()
        first = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint="f" * 64,
            product_sha="1" * 40,
        )
        later_cycle = replace(
            cycle,
            cycle_id="cycle-spcx-later",
            fingerprint="d" * 64,
        )
        later = build_continuous_paper_admission_intent(
            cycle=later_cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint="f" * 64,
            product_sha="1" * 40,
        )

        self.assertEqual(first.admission_id, later.admission_id)
        self.assertNotEqual(first.fingerprint, later.fingerprint)
        self.assertNotEqual(
            first.composition_cycle_fingerprint,
            later.composition_cycle_fingerprint,
        )

    def test_ineligible_plan_does_not_create_admission(self):
        cycle, member_result, universe_member = fixtures()
        ineligible = replace(
            member_result.intraday_plan,
            status="EXECUTION_INELIGIBLE",
        )

        self.assertIsNone(
            build_continuous_paper_admission_intent(
                cycle=cycle,
                member=replace(member_result, intraday_plan=ineligible),
                universe_member=universe_member,
                runtime_configuration_fingerprint="f" * 64,
                product_sha="1" * 40,
            )
        )


if __name__ == "__main__":
    unittest.main()
