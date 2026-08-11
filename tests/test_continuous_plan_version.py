from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    EXECUTION_ELIGIBLE,
    WATCHING,
    CandidateLifecycleSnapshot,
    expected_opportunity_id,
    expected_setup_id,
)
from momentum_hunter.catalyst_evidence import (
    CatalystEvidenceCoordinator,
    CatalystEvidencePolicy,
    CatalystEvidenceStore,
    CatalystObservation,
)
from momentum_hunter.continuous_plan_version import (
    ALLOCATION_AUTHORIZED,
    BLOCK_NEW_ENTRY,
    DECISION_AUTHORIZED,
    DECISION_NO_TRADE,
    EXECUTION_AUTHORITY,
    MANUAL_OVERRIDE,
    PLAN_BLOCKED,
    READY_FOR_RISK_REVIEW,
    RESEARCH_ONLY,
    RISK_AUTHORIZED,
    RISK_BLOCKED,
    RVOL_BLOCKED,
    RVOL_EXECUTION_ELIGIBLE,
    AllocationDecisionReference,
    ContinuousPlanError,
    ContinuousPlanPolicy,
    ContinuousPlanStore,
    RiskDecisionReference,
    RvolEvidence,
    SetupRevisionEvidence,
    SourceClockEvidence,
    build_continuous_plan_decision,
    build_continuous_plan_version,
    decision_fingerprint_payload,
    evidence_fingerprint,
    plan_fingerprint_payload,
    validate_decision,
    validate_plan_version,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    DIRECT_ISSUER,
)
from momentum_hunter.intraday_trade_plan import (
    CATALYST_DRIVER,
    CONTINUATION_BREAKOUT,
    TECHNICAL_DRIVER,
    build_intraday_plan_evidence,
)
from momentum_hunter.macro_event_context import (
    FED_DECISION,
    HIGH,
    MARKET,
    NORMAL,
    EventConsequenceRule,
    EventDefinition,
    EventRiskPolicy,
    EventRiskTarget,
    build_event_calendar,
    evaluate_event_risk,
)
from momentum_hunter.rolling_market_regime import (
    DATA_STALE,
    STALE,
    CandidateRegimeTarget,
    RegimeBar,
    RegimePolicy,
    derive_regime_snapshot,
    fan_out_regime_context,
)


CREATED = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
SESSION = "2026-08-10"
SYMBOL = "AAA"
SETUP_FINGERPRINT = "a" * 64
CONFIGURATION_FINGERPRINT = "f" * 64


class ContinuousPlanVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def bundle(self, **changes):
        setup_fingerprint = changes.pop("setup_fingerprint", SETUP_FINGERPRINT)
        setup_authority = changes.pop("setup_authority", EXECUTION_AUTHORITY)
        candidate_state = changes.pop("candidate_state", EXECUTION_ELIGIBLE)
        plan_driver = changes.pop("plan_driver", TECHNICAL_DRIVER)
        catalyst = changes.pop("catalyst", None)
        regime_stale = changes.pop("regime_stale", False)
        event_block = changes.pop("event_block", False)
        rvol_state = changes.pop("rvol_state", RVOL_EXECUTION_ELIGIBLE)
        revision_id = changes.pop("revision_id", "setup-revision-1")
        source_ids = changes.pop("source_ids", (revision_id, "bar-1"))
        if changes:
            raise AssertionError(f"Unsupported fixture changes: {changes}")

        opportunity_id = expected_opportunity_id(
            SYMBOL, SESSION, "CONTINUOUS_MONITOR"
        )
        setup_id = expected_setup_id(
            opportunity_id, CONTINUATION_BREAKOUT, 1
        )
        candidate = CandidateLifecycleSnapshot(
            opportunity_id=opportunity_id,
            symbol=SYMBOL,
            session_date=SESSION,
            originating_evidence_family="CONTINUOUS_MONITOR",
            current_state=candidate_state,
            last_non_stale_state=candidate_state,
            latest_event_id="b" * 64,
            latest_evidence_fingerprint=setup_fingerprint,
            current_setup_id=setup_id,
            current_setup_family=CONTINUATION_BREAKOUT,
            current_setup_sequence=1,
            latest_policy_fingerprint="c" * 64,
            updated_at=(CREATED - timedelta(seconds=20)).isoformat(),
        )
        setup = SetupRevisionEvidence(
            opportunity_id=opportunity_id,
            setup_id=setup_id,
            setup_family=CONTINUATION_BREAKOUT,
            setup_sequence=1,
            revision_id=revision_id,
            observed_at=(CREATED - timedelta(seconds=25)).isoformat(),
            evidence_fingerprint=setup_fingerprint,
            authority=setup_authority,
        )
        catalyst_relationship = ""
        catalyst_authority = ""
        catalyst_fingerprint = ""
        if plan_driver == CATALYST_DRIVER:
            catalyst_relationship = DIRECT_ISSUER
            catalyst_authority = CATALYST_SCORE_SUPPORTED
            catalyst_fingerprint = (
                catalyst.fingerprint if catalyst is not None else "9" * 64
            )
        intraday_plan = build_intraday_plan_evidence(
            symbol=SYMBOL,
            setup_family=CONTINUATION_BREAKOUT,
            created_at=CREATED,
            planned_entry=100.0,
            stop_price=98.0,
            target_prices=(102.0, 104.0),
            source_setup_fingerprint=setup_fingerprint,
            source_level_kind="SYNTHETIC_CONTINUOUS_STRUCTURE",
            source_evidence_ids=source_ids,
            setup_driver=plan_driver,
            catalyst_relationship_type=catalyst_relationship,
            catalyst_score_authority=catalyst_authority,
            catalyst_attribution_fingerprint=catalyst_fingerprint,
        )

        regime_policy = RegimePolicy(
            policy_version="synthetic-regime-v1",
            market_symbols=("SPY", "QQQ", "IWM"),
            short_window_bars=3,
            long_window_bars=6,
            volatility_baseline_bars=5,
            directional_return_threshold_pct=0.10,
            alignment_fraction=2 / 3,
            volatility_shock_multiple=5.0,
            sector_rotation_dispersion_pct=1.0,
            stale_after_seconds=90,
            maximum_cross_symbol_skew_seconds=5,
            maximum_internal_gap_seconds=65,
            minimum_sector_symbols=2,
            maximum_candidate_fan_out=3,
        )
        end = CREATED - (
            timedelta(minutes=5) if regime_stale else timedelta(seconds=30)
        )
        regime_bars = {
            symbol: synthetic_bars(symbol, end=end)
            for symbol in regime_policy.market_symbols
        }
        regime_snapshot = derive_regime_snapshot(
            bars_by_symbol=regime_bars,
            sector_symbols=(),
            policy=regime_policy,
            evaluated_at=CREATED - timedelta(seconds=10),
        )
        regime_context = fan_out_regime_context(
            regime_snapshot,
            (CandidateRegimeTarget(opportunity_id, SYMBOL),),
            policy=regime_policy,
        )[0]

        event_policy = EventRiskPolicy(
            policy_version="synthetic-event-v1",
            rules=(EventConsequenceRule(FED_DECISION, HIGH, BLOCK_NEW_ENTRY),),
            maximum_candidate_fan_out=3,
        )
        definitions = (blocking_event(),) if event_block else ()
        calendar = build_event_calendar(
            definitions=definitions,
            generated_at=CREATED - timedelta(hours=1),
            valid_through=CREATED + timedelta(hours=2),
        )
        event_context = evaluate_event_risk(
            calendar=calendar,
            policy=event_policy,
            evaluated_at=CREATED - timedelta(seconds=5),
            target=EventRiskTarget(opportunity_id, SYMBOL),
        )
        rvol = RvolEvidence(
            evidence_id="rvol-evidence-1",
            symbol=SYMBOL,
            session_date=SESSION,
            evaluated_at=(CREATED - timedelta(seconds=15)).isoformat(),
            evidence_fingerprint="d" * 64,
            authority_state=rvol_state,
        )
        clocks = (
            SourceClockEvidence(
                source_identity="synthetic-setup-source",
                provider_timestamp=(CREATED - timedelta(seconds=30)).isoformat(),
                receipt_timestamp=(CREATED - timedelta(seconds=29)).isoformat(),
                evidence_fingerprint=setup_fingerprint,
            ),
            SourceClockEvidence(
                source_identity="synthetic-rvol-source",
                provider_timestamp=(CREATED - timedelta(seconds=18)).isoformat(),
                receipt_timestamp=(CREATED - timedelta(seconds=17)).isoformat(),
                evidence_fingerprint=rvol.evidence_fingerprint,
            ),
        )
        return {
            "intraday_plan": intraday_plan,
            "candidate": candidate,
            "setup_revision": setup,
            "regime_snapshot": regime_snapshot,
            "regime_context": regime_context,
            "event_context": event_context,
            "rvol_evidence": rvol,
            "source_clocks": clocks,
            "policy": ContinuousPlanPolicy(
                policy_version="synthetic-continuous-plan-v1",
                configuration_fingerprint=CONFIGURATION_FINGERPRINT,
            ),
            "catalyst_snapshot": catalyst,
        }

    def build(self, **changes):
        return build_continuous_plan_version(**self.bundle(**changes))

    def test_valid_technical_plan_is_deterministic_and_ready_for_risk(self) -> None:
        first = self.build()
        second = self.build()

        self.assertEqual(first, second)
        self.assertEqual(READY_FOR_RISK_REVIEW, first.status)
        self.assertTrue(first.ready_for_risk_review)
        self.assertEqual((), first.blockers)
        self.assertEqual(1, first.version_number)
        validate_plan_version(first)

    def test_research_only_setup_cannot_gain_authority_from_plan_wrapper(self) -> None:
        plan = self.build(setup_authority=RESEARCH_ONLY)

        self.assertEqual(PLAN_BLOCKED, plan.status)
        self.assertIn("SETUP_EVIDENCE_RESEARCH_ONLY", plan.blockers)
        self.assertFalse(plan.ready_for_risk_review)

    def test_candidate_regime_event_and_rvol_gates_fail_closed(self) -> None:
        cases = {
            "candidate": (
                {"candidate_state": WATCHING},
                "CANDIDATE_NOT_EXECUTION_ELIGIBLE",
            ),
            "regime": ({"regime_stale": True}, "REGIME_EVIDENCE_UNSAFE"),
            "event": ({"event_block": True}, "MACRO_EVENT_BLOCKS_NEW_ENTRY"),
            "rvol": (
                {"rvol_state": RVOL_BLOCKED},
                "RVOL_EVIDENCE_NOT_EXECUTION_ELIGIBLE",
            ),
        }
        for name, (changes, blocker) in cases.items():
            with self.subTest(name=name):
                plan = self.build(**changes)
                self.assertEqual(PLAN_BLOCKED, plan.status)
                self.assertIn(blocker, plan.blockers)

    def test_catalyst_plan_requires_current_supported_snapshot(self) -> None:
        missing = self.build(plan_driver=CATALYST_DRIVER)
        catalyst = self.catalyst_snapshot()
        supported = self.build(
            plan_driver=CATALYST_DRIVER,
            catalyst=catalyst,
        )

        self.assertIn("CATALYST_EVIDENCE_REQUIRED", missing.blockers)
        self.assertEqual(READY_FOR_RISK_REVIEW, supported.status)
        self.assertEqual(catalyst.fingerprint, supported.catalyst_snapshot_fingerprint)

    def test_cross_symbol_session_setup_and_source_mismatches_are_rejected(self) -> None:
        cases = []
        base = self.bundle()
        cases.append(("candidate symbol", {**base, "candidate": replace(base["candidate"], symbol="BBB")}))
        cases.append(("regime target", {**base, "regime_context": replace(base["regime_context"], symbol="BBB")}))
        cases.append(("event target", {**base, "event_context": replace(base["event_context"], target_symbol="BBB")}))
        cases.append(("rvol session", {**base, "rvol_evidence": replace(base["rvol_evidence"], session_date="2026-08-11")}))
        cases.append(("missing setup source", {**self.bundle(source_ids=("bar-1",))}))
        for name, values in cases:
            with self.subTest(name=name):
                with self.assertRaises(ContinuousPlanError):
                    build_continuous_plan_version(**values)

    def test_future_evidence_and_backward_source_clock_are_rejected(self) -> None:
        base = self.bundle()
        future = replace(
            base["setup_revision"],
            observed_at=(CREATED + timedelta(seconds=1)).isoformat(),
        )
        with self.assertRaisesRegex(ContinuousPlanError, "after plan creation"):
            build_continuous_plan_version(**{**base, "setup_revision": future})

        bad_clock = replace(
            base["source_clocks"][0],
            provider_timestamp=(CREATED - timedelta(seconds=1)).isoformat(),
            receipt_timestamp=(CREATED - timedelta(seconds=2)).isoformat(),
        )
        with self.assertRaisesRegex(ContinuousPlanError, "predates provider"):
            build_continuous_plan_version(
                **{**base, "source_clocks": (bad_clock, base["source_clocks"][1])}
            )

    def test_material_successor_is_new_version_and_preserves_predecessor(self) -> None:
        first = self.build()
        second_bundle = self.bundle(
            setup_fingerprint="e" * 64,
            revision_id="setup-revision-2",
        )
        second = build_continuous_plan_version(
            **second_bundle,
            predecessor=first,
            supersession_reason="CONTEXT_REFRESH",
        )

        self.assertEqual(2, second.version_number)
        self.assertNotEqual(first.plan_version_id, second.plan_version_id)
        self.assertEqual(first.plan_version_id, second.predecessor_plan_version_id)
        self.assertEqual(first.fingerprint, second.predecessor_plan_version_fingerprint)

    def test_successor_requires_reason_and_new_plan_evidence(self) -> None:
        first = self.build()
        with self.assertRaisesRegex(ContinuousPlanError, "reason"):
            build_continuous_plan_version(**self.bundle(), predecessor=first)
        with self.assertRaisesRegex(ContinuousPlanError, "new IntradayPlan"):
            build_continuous_plan_version(
                **self.bundle(),
                predecessor=first,
                supersession_reason="CONTEXT_REFRESH",
            )

    def test_store_is_append_only_idempotent_and_detects_tampering(self) -> None:
        path = self.root / "plans.json"
        store = ContinuousPlanStore(path)
        plan = self.build()
        store.append(plan)
        before = path.read_bytes()

        self.assertEqual(plan, store.append(plan))
        self.assertEqual(before, path.read_bytes())
        self.assertEqual((plan,), store.load().plans)

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["plans"][0]["symbol"] = "BBB"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ContinuousPlanError, "fingerprint"):
            store.load()

    def test_source_objects_are_not_mutated(self) -> None:
        bundle = self.bundle()
        before = repr(bundle)

        build_continuous_plan_version(**bundle)

        self.assertEqual(before, repr(bundle))

    def test_required_source_clocks_cannot_be_omitted(self) -> None:
        bundle = self.bundle()

        with self.assertRaisesRegex(ContinuousPlanError, "RVOL evidence"):
            build_continuous_plan_version(
                **{**bundle, "source_clocks": bundle["source_clocks"][:1]}
            )

    def test_validator_rederives_authority_instead_of_trusting_forged_status(self) -> None:
        blocked = self.build(setup_authority=RESEARCH_ONLY)
        forged = replace(
            blocked,
            status=READY_FOR_RISK_REVIEW,
            blockers=(),
            plan_version_id="",
            fingerprint="",
        )
        fingerprint = evidence_fingerprint(plan_fingerprint_payload(forged))
        forged = replace(
            forged,
            plan_version_id=f"continuous-plan-{fingerprint[:24]}",
            fingerprint=fingerprint,
        )

        with self.assertRaisesRegex(ContinuousPlanError, "required authority blocker"):
            validate_plan_version(forged)

    def test_store_rejects_branching_from_an_old_opportunity_version(self) -> None:
        store = ContinuousPlanStore(self.root / "chain.json")
        first = self.build()
        second = build_continuous_plan_version(
            **self.bundle(
                setup_fingerprint="e" * 64,
                revision_id="setup-revision-2",
            ),
            predecessor=first,
            supersession_reason="CONTEXT_REFRESH",
        )
        branch = build_continuous_plan_version(
            **self.bundle(
                setup_fingerprint="7" * 64,
                revision_id="setup-revision-branch",
            ),
            predecessor=first,
            supersession_reason="CONTEXT_REFRESH",
        )
        store.append(first)
        store.append(second)

        with self.assertRaisesRegex(ContinuousPlanError, "latest opportunity"):
            store.append(branch)
        self.assertEqual((first, second), store.load().plans)

    def test_authorized_decision_binds_exact_plan_risk_allocation_and_clock(self) -> None:
        plan = self.build()
        risk = self.risk(plan)
        allocation = self.allocation(plan, risk)
        decision = build_continuous_plan_decision(
            plan_version=plan,
            intraday_plan=self.bundle()["intraday_plan"],
            risk=risk,
            allocation=allocation,
            decided_at=CREATED + timedelta(minutes=1),
            mode="ALPACA_PAPER_ENGINEERING",
        )

        self.assertEqual(DECISION_AUTHORIZED, decision.status)
        self.assertTrue(decision.authorized)
        self.assertEqual(risk.risk_decision_id, decision.risk_decision_id)
        self.assertEqual(allocation.evidence_fingerprint, decision.allocation_decision_fingerprint)
        validate_decision(decision)

    def test_blocked_risk_or_allocation_produces_explicit_no_trade(self) -> None:
        plan = self.build()
        risk = replace(self.risk(plan), status=RISK_BLOCKED)
        allocation = self.allocation(plan, risk)
        decision = build_continuous_plan_decision(
            plan_version=plan,
            intraday_plan=self.bundle()["intraday_plan"],
            risk=risk,
            allocation=allocation,
            decided_at=CREATED + timedelta(minutes=1),
            mode="FAKEBROKER",
        )

        self.assertEqual(DECISION_NO_TRADE, decision.status)
        self.assertIn("RISK_DECISION_BLOCKED", decision.blockers)
        self.assertFalse(decision.authorized)

    def test_live_mode_and_cross_plan_allocation_are_rejected(self) -> None:
        plan = self.build()
        risk = self.risk(plan)
        allocation = self.allocation(plan, risk)
        arguments = {
            "plan_version": plan,
            "intraday_plan": self.bundle()["intraday_plan"],
            "risk": risk,
            "allocation": allocation,
            "decided_at": CREATED + timedelta(minutes=1),
        }
        with self.assertRaisesRegex(ContinuousPlanError, "live mode"):
            build_continuous_plan_decision(**arguments, mode="LIVE")
        with self.assertRaisesRegex(ContinuousPlanError, "risk decision"):
            build_continuous_plan_decision(
                **{
                    **arguments,
                    "allocation": replace(allocation, risk_decision_id="other-risk"),
                },
                mode="FAKEBROKER",
            )

    def test_decision_validator_rejects_forged_authorized_zero_quantity(self) -> None:
        plan = self.build()
        risk = self.risk(plan)
        allocation = self.allocation(plan, risk)
        decision = build_continuous_plan_decision(
            plan_version=plan,
            intraday_plan=self.bundle()["intraday_plan"],
            risk=risk,
            allocation=allocation,
            decided_at=CREATED + timedelta(minutes=1),
            mode="FAKEBROKER",
        )
        forged = replace(decision, final_authorized_quantity="0", fingerprint="")
        forged = replace(
            forged,
            fingerprint=evidence_fingerprint(decision_fingerprint_payload(forged)),
        )

        with self.assertRaisesRegex(ContinuousPlanError, "quantity must be positive"):
            validate_decision(forged)

    def test_manual_override_requires_new_plan_risk_and_allocation(self) -> None:
        first = self.build()
        first_risk = self.risk(first)
        first_allocation = self.allocation(first, first_risk)
        first_decision = build_continuous_plan_decision(
            plan_version=first,
            intraday_plan=self.bundle()["intraday_plan"],
            risk=first_risk,
            allocation=first_allocation,
            decided_at=CREATED + timedelta(minutes=1),
            mode="FAKEBROKER",
        )
        second_bundle = self.bundle(
            setup_fingerprint="e" * 64,
            revision_id="setup-revision-2",
        )
        second = build_continuous_plan_version(
            **second_bundle,
            predecessor=first,
            supersession_reason=MANUAL_OVERRIDE,
        )
        reused_risk = replace(first_risk, intraday_plan_id=second.intraday_plan_id)
        reused_allocation = replace(
            first_allocation,
            intraday_plan_id=second.intraday_plan_id,
        )
        with self.assertRaisesRegex(ContinuousPlanError, "new risk"):
            build_continuous_plan_decision(
                plan_version=second,
                intraday_plan=second_bundle["intraday_plan"],
                risk=reused_risk,
                allocation=reused_allocation,
                decided_at=CREATED + timedelta(minutes=2),
                mode="FAKEBROKER",
                predecessor_decision=first_decision,
            )

        second_risk = self.risk(second, identity="risk-decision-2", fingerprint="7" * 64)
        second_allocation = self.allocation(
            second, second_risk, cycle="cycle-2", fingerprint="8" * 64
        )
        approved = build_continuous_plan_decision(
            plan_version=second,
            intraday_plan=second_bundle["intraday_plan"],
            risk=second_risk,
            allocation=second_allocation,
            decided_at=CREATED + timedelta(minutes=2),
            mode="FAKEBROKER",
            predecessor_decision=first_decision,
        )
        self.assertEqual(DECISION_AUTHORIZED, approved.status)

    def test_module_has_no_network_broker_order_scoring_or_runtime_capability(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "continuous_plan_version.py"
        )
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
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
        forbidden_imports = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "schwab_market_data",
            "broker",
            "execution",
            "engine_host",
            "shadow",
            "scoring",
        )
        self.assertFalse(
            [name for name in imports if any(part in name for part in forbidden_imports)]
        )
        for forbidden_text in (
            "submit_order",
            "cancel_order",
            "replace_order",
            "query_account",
            "build_trade_planning_report",
        ):
            self.assertNotIn(forbidden_text, source)

    def catalyst_snapshot(self):
        path = self.root / "catalyst.json"
        policy = CatalystEvidencePolicy(
            policy_version="synthetic-catalyst-v1",
            maximum_age_seconds=300,
            future_tolerance_seconds=5,
            material_delta_profile="material-v1",
        )
        coordinator = CatalystEvidenceCoordinator(
            CatalystEvidenceStore(path), policy=policy
        )
        result = coordinator.observe(
            CatalystObservation(
                source_identity="synthetic-catalyst-source",
                source_article_id="article-1",
                provider="synthetic-provider",
                source_name="Synthetic Wire",
                candidate_symbol=SYMBOL,
                candidate_company="AAA Corp",
                headline="AAA raises same-session guidance",
                summary="AAA explicitly raised guidance.",
                published_at=(CREATED - timedelta(minutes=2)).isoformat(),
                provider_timestamp=(CREATED - timedelta(seconds=50)).isoformat(),
                receipt_timestamp=(CREATED - timedelta(seconds=49)).isoformat(),
                relationship_type=DIRECT_ISSUER,
                relationship_evidence="The issuer is explicitly named.",
                score_authority=CATALYST_SCORE_SUPPORTED,
            )
        )
        return coordinator.snapshots(
            evaluated_at=CREATED - timedelta(seconds=5),
        )[0]

    @staticmethod
    def risk(plan, *, identity="risk-decision-1", fingerprint="1" * 64):
        return RiskDecisionReference(
            risk_decision_id=identity,
            intraday_plan_id=plan.intraday_plan_id,
            setup_id=plan.setup_id,
            status=RISK_AUTHORIZED,
            policy_fingerprint="2" * 64,
            evidence_fingerprint=fingerprint,
        )

    @staticmethod
    def allocation(plan, risk, *, cycle="cycle-1", fingerprint="3" * 64):
        return AllocationDecisionReference(
            decision_cycle_id=cycle,
            intraday_plan_id=plan.intraday_plan_id,
            risk_decision_id=risk.risk_decision_id,
            status=ALLOCATION_AUTHORIZED,
            final_authorized_quantity="0.250000000",
            policy_fingerprint="4" * 64,
            account_snapshot_fingerprint="5" * 64,
            capability_registry_fingerprint="6" * 64,
            evidence_fingerprint=fingerprint,
        )


def synthetic_bars(symbol: str, *, end: datetime) -> tuple[RegimeBar, ...]:
    start = end - timedelta(minutes=7)
    return tuple(
        RegimeBar(
            symbol=symbol,
            timestamp=(start + timedelta(minutes=index)).isoformat(),
            open=100.0 + (index * 0.1),
            high=100.1 + (index * 0.1),
            low=99.9 + (index * 0.1),
            close=100.05 + (index * 0.1),
            volume=1000 + index,
            source_identity="synthetic-canonical-bars",
            source_state="RECONCILED",
        )
        for index in range(8)
    )


def blocking_event() -> EventDefinition:
    return EventDefinition(
        source_event_id="fed-1",
        revision_identity="revision-1",
        category=FED_DECISION,
        title="Synthetic Fed decision",
        importance=HIGH,
        evidence_state="CURRENT",
        scheduled_start=(CREATED - timedelta(minutes=1)).isoformat(),
        scheduled_end=(CREATED + timedelta(minutes=4)).isoformat(),
        risk_window_start=(CREATED - timedelta(minutes=15)).isoformat(),
        risk_window_end=(CREATED + timedelta(minutes=30)).isoformat(),
        observation_window_start=(CREATED - timedelta(minutes=30)).isoformat(),
        observation_window_end=(CREATED + timedelta(hours=1)).isoformat(),
        scope=MARKET,
        source_identity="synthetic-calendar",
        provider_timestamp=(CREATED - timedelta(hours=2)).isoformat(),
        receipt_timestamp=(CREATED - timedelta(hours=2) + timedelta(seconds=1)).isoformat(),
    )


if __name__ == "__main__":
    unittest.main()
