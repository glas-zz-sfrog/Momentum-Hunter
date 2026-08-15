from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from momentum_hunter.opportunity_denominator import (
    ACTUAL_SYSTEM_DECISION,
    AT_DECISION,
    BLOCKED_DATA,
    BROKER_EXECUTION,
    CANCELLED,
    COUNTERFACTUAL_RESEARCH_OBSERVATION,
    DATA_FAILURE,
    DENOMINATOR_INCOMPLETE,
    ELIGIBLE_NOT_SELECTED,
    ELIGIBLE_SELECTED,
    EXECUTION_AUTHORITY_NONE,
    FULL_FILL,
    INVALIDATED,
    MARKET_PATH,
    MOMENTUM_CANDIDATE,
    NO_ACTION_RESEARCH_ONLY,
    NOT_EVALUATED_PROVIDER_BOUND,
    PARTIAL_FILL,
    POLICY_FINGERPRINT,
    POST_DECISION_RESEARCH,
    PRE_DECISION,
    PROSPECTIVE,
    PROVIDER_BOUND_ROW,
    RANK_ALTERNATIVE,
    REJECTED_STRATEGY,
    RESOLVED,
    RETROSPECTIVE_RESEARCH_EXAMPLE,
    SAMPLE_IDENTITY,
    SAMPLE_STATUS,
    SPECIALIST_NOMINATION,
    STOP_FIRST,
    SYNTHETIC_TEST,
    SYSTEM_FAILURE,
    TARGET_FIRST,
    TIMEOUT,
    UNFILLED,
    UNRESOLVED,
    UNTRIGGERED,
    BrokerExecutionOutcomeRecord,
    DenominatorPolicy,
    MarketPathBar,
    OpportunityDenominatorError,
    OpportunityDenominatorStore,
    OpportunitySeed,
    adapt_opening_report,
    build_broker_execution_outcome,
    build_cycle_bundle,
    build_data_quality_outcome,
    build_market_path_outcome,
    build_specialist_attachment,
    current_policy,
    validate_cycle,
    validate_opportunity,
    validate_outcome,
)
from momentum_hunter.specialist_opinion import (
    BULLISH,
    EVALUATED,
    HEURISTIC,
    UNCALIBRATED,
    build_confidence,
    build_evidence_reference,
    build_specialist_opinion,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


BASE_TIME = "2026-08-14T13:35:00Z"
CUTOFF = "2026-08-14T13:36:00Z"


class OpportunityDenominatorTests(unittest.TestCase):
    def evidence(self, name: str = "row", at: str = BASE_TIME):
        return build_evidence_reference(
            evidence_id=f"evidence:{name}",
            evidence_type="OPENING_ROW",
            source="synthetic-test",
            as_of=at,
            fingerprint=h(name),
        )

    def seed(
        self,
        *,
        symbol: str = "NVDA",
        rank: int = 1,
        setup: str = "setup-a",
        origin_record: str = "row:1",
        observed_at: str = BASE_TIME,
        cutoff: str = CUTOFF,
        disposition: str = ELIGIBLE_SELECTED,
        decision_class: str = ACTUAL_SYSTEM_DECISION,
        origins: tuple[str, ...] = (MOMENTUM_CANDIDATE,),
        security_status: str = UNRESOLVED,
        security_id: str | None = None,
        candidate_id: str | None = "candidate:1",
    ) -> OpportunitySeed:
        return OpportunitySeed(
            origin_kinds=origins,
            origin_record_id=origin_record,
            origin_fingerprint=h(origin_record),
            symbol=symbol,
            security_identity_status=security_status,
            security_id=security_id,
            observed_at=observed_at,
            decision_cutoff=cutoff,
            candidate_id=candidate_id,
            setup_id=h(setup),
            trade_plan_id=h(f"plan:{setup}"),
            rank=rank,
            evidence_refs=(self.evidence(f"{origin_record}:{setup}", observed_at),),
            disposition=disposition,
            decision_class=decision_class,
        )

    def cycle(
        self,
        seeds: list[OpportunitySeed] | None = None,
        *,
        raw: int | None = None,
        parsed: int | None = None,
        mode: str = SYNTHETIC_TEST,
        failure_reason: str | None = None,
        policy: DenominatorPolicy | None = None,
        source: str = "source:one",
    ):
        rows = seeds if seeds is not None else [self.seed()]
        count = len(rows)
        return build_cycle_bundle(
            cycle_type="OPENING_MOMENTUM",
            session_date="2026-08-14",
            session_type="REGULAR",
            observed_at=BASE_TIME,
            decision_cutoff=CUTOFF,
            source_identity=source,
            source_evidence_fingerprint=h(source),
            raw_count=count if raw is None else raw,
            parsed_count=count if parsed is None else parsed,
            seeds=rows,
            observation_mode=mode,
            failure_reason=failure_reason,
            policy=policy,
        )

    def opinion(self, opportunity, *, at: str = BASE_TIME, candidate=None, setup=None, plan=None):
        evidence = self.evidence("opinion", at)
        return build_specialist_opinion(
            specialist_id="REGIME",
            specialist_version="regime-test-v1",
            opportunity_id=opportunity.opportunity_id,
            candidate_id=opportunity.candidate_id if candidate is None else candidate,
            setup_id=opportunity.setup_id if setup is None else setup,
            trade_plan_id=opportunity.trade_plan_id if plan is None else plan,
            as_of=at,
            expires_at="2026-08-14T14:00:00Z",
            research_identity="regime-research-v1",
            policy_fingerprint=h("regime-policy"),
            evaluation_status=EVALUATED,
            opinion_code="SUPPORTIVE",
            directional_bias=BULLISH,
            evidence_refs=(evidence,),
            feature_families=("MARKET_REGIME",),
            confidence=build_confidence(
                value=0.8,
                kind=HEURISTIC,
                calibration_status=UNCALIBRATED,
                sample_size=None,
                model_version="regime-test-v1",
            ),
            reason_codes=("TREND_SUPPORTIVE",),
        )

    def bar(self, minute: int, *, high: float, low: float, open_: float = 100.0, close: float = 100.0):
        timestamp = f"2026-08-14T13:{minute:02d}:00Z"
        return MarketPathBar(
            timestamp=timestamp,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=1000,
            evidence_id=f"bar:{minute}",
            fingerprint=h(f"bar:{minute}:{high}:{low}"),
        )

    def test_inactive_sample_is_zero_and_has_no_authority(self):
        policy = current_policy()
        self.assertEqual(SAMPLE_STATUS, policy.status)
        self.assertEqual(SAMPLE_IDENTITY, policy.sample_identity)
        self.assertEqual(POLICY_FINGERPRINT, policy.policy_fingerprint)
        self.assertEqual(EXECUTION_AUTHORITY_NONE, policy.execution_authority)
        with tempfile.TemporaryDirectory() as directory:
            summary = OpportunityDenominatorStore(Path(directory)).summary()
        self.assertEqual(0, summary.prospective_sessions)
        self.assertEqual(0, summary.total_opportunities)

    def test_same_symbol_same_day_two_legitimate_opportunities_are_distinct(self):
        first = self.seed(setup="opening", origin_record="row:1")
        second = self.seed(
            setup="reclaim",
            origin_record="continuous:2",
            observed_at="2026-08-14T15:00:00Z",
            cutoff="2026-08-14T15:01:00Z",
            origins=(MOMENTUM_CANDIDATE, RANK_ALTERNATIVE),
        )
        _, rows = self.cycle([first, second])
        self.assertNotEqual(rows[0].opportunity_id, rows[1].opportunity_id)

    def test_same_setup_exact_replay_is_deterministic(self):
        first = self.cycle()
        second = self.cycle()
        self.assertEqual(first, second)

    def test_cycle_twenty_rows_only_five_represented_is_incomplete(self):
        rows = [self.seed(rank=index, setup=f"s{index}", origin_record=f"row:{index}") for index in range(1, 6)]
        cycle, opportunities = self.cycle(rows, raw=20, parsed=20)
        self.assertFalse(cycle.complete_denominator)
        self.assertEqual(DENOMINATOR_INCOMPLETE, cycle.failure_reason)
        self.assertEqual(5, len(opportunities))

    def test_provider_bound_rows_must_be_explicit_denominator_members(self):
        evaluated = self.seed()
        missing_cycle, _ = self.cycle([evaluated], raw=2, parsed=2)
        self.assertFalse(missing_cycle.complete_denominator)
        provider = self.seed(
            rank=2,
            setup="provider",
            origin_record="row:2",
            disposition=NOT_EVALUATED_PROVIDER_BOUND,
            origins=(PROVIDER_BOUND_ROW, RANK_ALTERNATIVE),
        )
        complete_cycle, rows = self.cycle([evaluated, provider], raw=2, parsed=2)
        self.assertTrue(complete_cycle.complete_denominator)
        self.assertEqual(1, complete_cycle.not_evaluated_count)
        self.assertEqual(2, len(rows))

    def test_duplicate_opportunity_identity_rejected(self):
        seed = self.seed()
        with self.assertRaisesRegex(OpportunityDenominatorError, "Duplicate opportunity"):
            self.cycle([seed, seed])

    def test_ticker_cannot_be_promoted_to_durable_security_identity(self):
        with self.assertRaisesRegex(OpportunityDenominatorError, "Ticker alone"):
            self.cycle([self.seed(security_status=RESOLVED, security_id="NVDA")])
        cycle, rows = self.cycle([self.seed(security_status=RESOLVED, security_id="FIGI:BBG000BBJQV7")])
        self.assertTrue(cycle.complete_denominator)
        self.assertEqual(RESOLVED, rows[0].security_identity_status)

    def test_specialist_nomination_requires_lineage_but_has_no_authority(self):
        seed = replace(
            self.seed(origins=(SPECIALIST_NOMINATION,)),
            nominating_specialist_id="TECHNICAL_STRUCTURE",
            nomination_opinion_fingerprint=h("nomination"),
        )
        _, rows = self.cycle([seed])
        self.assertEqual(EXECUTION_AUTHORITY_NONE, rows[0].execution_authority)
        with self.assertRaisesRegex(OpportunityDenominatorError, "requires specialist"):
            self.cycle([self.seed(origins=(SPECIALIST_NOMINATION,))])

    def test_wrong_symbol_attachment_rejected(self):
        _, rows = self.cycle()
        with self.assertRaisesRegex(OpportunityDenominatorError, "symbol"):
            build_specialist_attachment(
                opportunity=rows[0], opinion=self.opinion(rows[0]), opinion_symbol="MSFT", attached_at=CUTOFF
            )

    def test_wrong_candidate_setup_and_tradeplan_attachments_rejected(self):
        _, rows = self.cycle()
        opportunity = rows[0]
        cases = [
            {"candidate": "candidate:wrong"},
            {"setup": h("wrong-setup")},
            {"plan": h("wrong-plan")},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(OpportunityDenominatorError):
                build_specialist_attachment(
                    opportunity=opportunity,
                    opinion=self.opinion(opportunity, **case),
                    opinion_symbol="NVDA",
                    attached_at=CUTOFF,
                )

    def test_specialist_timing_is_derived_not_caller_labeled(self):
        _, rows = self.cycle()
        opportunity = rows[0]
        pre = build_specialist_attachment(
            opportunity=opportunity,
            opinion=self.opinion(opportunity, at=BASE_TIME),
            opinion_symbol="NVDA",
            attached_at=CUTOFF,
        )
        self.assertEqual(PRE_DECISION, pre.timing_relationship)
        at = build_specialist_attachment(
            opportunity=opportunity,
            opinion=self.opinion(opportunity, at=CUTOFF),
            opinion_symbol="NVDA",
            attached_at="2026-08-14T13:37:00Z",
        )
        self.assertEqual(AT_DECISION, at.timing_relationship)
        post = build_specialist_attachment(
            opportunity=opportunity,
            opinion=self.opinion(opportunity, at="2026-08-14T13:37:00Z"),
            opinion_symbol="NVDA",
            attached_at="2026-08-14T13:38:00Z",
        )
        self.assertEqual(POST_DECISION_RESEARCH, post.timing_relationship)

    def test_future_dated_and_tampered_specialist_opinions_rejected(self):
        _, rows = self.cycle()
        opportunity = rows[0]
        future = self.opinion(opportunity, at="2026-08-14T13:37:00Z")
        with self.assertRaisesRegex(OpportunityDenominatorError, "Future-dated"):
            build_specialist_attachment(
                opportunity=opportunity,
                opinion=future,
                opinion_symbol="NVDA",
                attached_at=CUTOFF,
            )
        tampered = replace(self.opinion(opportunity), fingerprint=h("tampered"))
        with self.assertRaises(OpportunityDenominatorError):
            build_specialist_attachment(
                opportunity=opportunity,
                opinion=tampered,
                opinion_symbol="NVDA",
                attached_at=CUTOFF,
            )

    def test_target_first_metrics_stop_at_terminal_bar(self):
        _, rows = self.cycle()
        opportunity = rows[0]
        bars = [
            self.bar(36, high=101, low=99, close=100.5),
            self.bar(37, high=103, low=100, open_=101, close=102),
            self.bar(38, high=150, low=50, open_=102, close=120),
            self.bar(39, high=120, low=90, open_=110, close=100),
        ]
        outcome = build_market_path_outcome(
            opportunity=opportunity,
            bars=bars,
            entry_price=101,
            stop_price=98,
            target_price=103,
            horizon_end="2026-08-14T13:39:00Z",
            observation_class=ACTUAL_SYSTEM_DECISION,
        )
        self.assertEqual(TARGET_FIRST, outcome.outcome_state)
        self.assertEqual("2026-08-14T13:37:00Z", outcome.terminal_timestamp)
        self.assertEqual(2.0, outcome.mfe)
        self.assertEqual(2.0, outcome.mae)

    def test_same_bar_trigger_and_stop_is_ambiguous(self):
        _, rows = self.cycle()
        outcome = build_market_path_outcome(
            opportunity=rows[0],
            bars=[self.bar(36, high=102, low=97)],
            entry_price=101,
            stop_price=98,
            target_price=103,
            horizon_end="2026-08-14T13:36:00Z",
            observation_class=ACTUAL_SYSTEM_DECISION,
        )
        self.assertEqual("AMBIGUOUS_SAME_BAR", outcome.outcome_state)

    def test_stop_timeout_untriggered_invalidated_and_data_failure(self):
        _, rows = self.cycle()
        opportunity = rows[0]
        cases = [
            ([self.bar(36, high=101, low=99), self.bar(37, high=101, low=97)], "2026-08-14T13:37:00Z", STOP_FIRST),
            ([self.bar(36, high=101, low=99), self.bar(37, high=102, low=99)], "2026-08-14T13:37:00Z", TIMEOUT),
            ([self.bar(36, high=100, low=99), self.bar(37, high=100, low=99)], "2026-08-14T13:37:00Z", UNTRIGGERED),
            ([self.bar(36, high=100, low=97)], "2026-08-14T13:36:00Z", INVALIDATED),
            ([self.bar(36, high=100, low=99)], "2026-08-14T13:37:00Z", DATA_FAILURE),
        ]
        for bars, horizon, expected in cases:
            with self.subTest(expected=expected):
                outcome = build_market_path_outcome(
                    opportunity=opportunity,
                    bars=bars,
                    entry_price=101,
                    stop_price=98,
                    target_price=103,
                    horizon_end=horizon,
                    observation_class=ACTUAL_SYSTEM_DECISION,
                )
                self.assertEqual(expected, outcome.outcome_state)

    def test_outcome_before_opportunity_and_horizon_before_cutoff_rejected(self):
        _, rows = self.cycle()
        with self.assertRaisesRegex(OpportunityDenominatorError, "predates opportunity"):
            build_market_path_outcome(
                opportunity=rows[0],
                bars=[MarketPathBar("2026-08-14T13:34:00Z", 100, 101, 99, 100, 1, "bar:old", h("old"))],
                entry_price=101,
                stop_price=98,
                target_price=103,
                horizon_end="2026-08-14T13:36:00Z",
                observation_class=ACTUAL_SYSTEM_DECISION,
            )
        with self.assertRaisesRegex(OpportunityDenominatorError, "horizon precedes"):
            build_market_path_outcome(
                opportunity=rows[0],
                bars=[],
                entry_price=101,
                stop_price=98,
                target_price=103,
                horizon_end=BASE_TIME,
                observation_class=ACTUAL_SYSTEM_DECISION,
            )

    def test_counterfactual_cannot_be_mislabeled_actual(self):
        _, rows = self.cycle(
            [self.seed(disposition=ELIGIBLE_NOT_SELECTED, decision_class=ACTUAL_SYSTEM_DECISION)]
        )
        with self.assertRaisesRegex(OpportunityDenominatorError, "must remain counterfactual"):
            build_market_path_outcome(
                opportunity=rows[0],
                bars=[self.bar(36, high=100, low=99)],
                entry_price=101,
                stop_price=98,
                target_price=103,
                horizon_end="2026-08-14T13:36:00Z",
                observation_class=ACTUAL_SYSTEM_DECISION,
            )

    def broker_kwargs(self, opportunity):
        return dict(
            opportunity=opportunity,
            outcome_state=FULL_FILL,
            submission_id="alpaca-paper:order:1",
            submission_fingerprint=h("submission"),
            provider_evidence_id="alpaca-paper:response:1",
            provider_evidence_fingerprint=h("provider"),
            provider_order_status="FILLED",
            requested_quantity=0.5,
            requested_notional=None,
            filled_quantity=0.5,
            average_fill_price=101.25,
            fill_time="2026-08-14T13:37:00Z",
            remaining_quantity=0,
            observed_at="2026-08-14T13:37:01Z",
        )

    def test_actual_broker_fill_requires_selected_actual_opportunity(self):
        _, selected = self.cycle()
        outcome = build_broker_execution_outcome(**self.broker_kwargs(selected[0]))
        self.assertEqual(BROKER_EXECUTION, outcome.outcome_domain)
        _, rejected = self.cycle(
            [self.seed(disposition=REJECTED_STRATEGY, decision_class=ACTUAL_SYSTEM_DECISION)],
            source="source:rejected",
        )
        with self.assertRaisesRegex(OpportunityDenominatorError, "actual selected"):
            build_broker_execution_outcome(**self.broker_kwargs(rejected[0]))

    def test_unfilled_requires_submission_and_provider_evidence(self):
        _, rows = self.cycle()
        kwargs = self.broker_kwargs(rows[0])
        kwargs.update(
            outcome_state=UNFILLED,
            provider_order_status="NEW",
            filled_quantity=0,
            average_fill_price=None,
            fill_time=None,
            remaining_quantity=0.5,
        )
        self.assertEqual(UNFILLED, build_broker_execution_outcome(**kwargs).outcome_state)
        kwargs["submission_id"] = ""
        with self.assertRaises(OpportunityDenominatorError):
            build_broker_execution_outcome(**kwargs)

    def test_partial_fill_cannot_be_labeled_full(self):
        _, rows = self.cycle()
        kwargs = self.broker_kwargs(rows[0])
        kwargs["filled_quantity"] = 0.25
        with self.assertRaisesRegex(OpportunityDenominatorError, "Partial fill"):
            build_broker_execution_outcome(**kwargs)
        kwargs.update(
            outcome_state=PARTIAL_FILL,
            provider_order_status="PARTIALLY_FILLED",
            remaining_quantity=0.25,
        )
        partial = build_broker_execution_outcome(**kwargs)
        self.assertEqual(PARTIAL_FILL, partial.outcome_state)

    def test_market_path_cannot_be_persisted_as_broker_execution(self):
        _, rows = self.cycle()
        market = build_market_path_outcome(
            opportunity=rows[0],
            bars=[self.bar(36, high=100, low=99)],
            entry_price=101,
            stop_price=98,
            target_price=103,
            horizon_end="2026-08-14T13:36:00Z",
            observation_class=ACTUAL_SYSTEM_DECISION,
        )
        tampered = replace(market, outcome_domain=BROKER_EXECUTION)
        with self.assertRaisesRegex(OpportunityDenominatorError, "domain"):
            validate_outcome(tampered)

    def test_data_and_system_failures_remain_cycles_not_strategy_rejections(self):
        failed_cycle, rows = self.cycle([], raw=0, parsed=0, failure_reason=SYSTEM_FAILURE)
        self.assertFalse(failed_cycle.complete_denominator)
        data = build_data_quality_outcome(
            cycle=failed_cycle,
            outcome_state=SYSTEM_FAILURE,
            observed_at=CUTOFF,
            reason_codes=("UPSTREAM_UNAVAILABLE",),
        )
        self.assertEqual(SYSTEM_FAILURE, data.outcome_state)
        rejected_cycle, rejected_rows = self.cycle(
            [self.seed(disposition=REJECTED_STRATEGY)], source="source:reject"
        )
        with self.assertRaisesRegex(OpportunityDenominatorError, "mislabeled strategy"):
            build_data_quality_outcome(
                cycle=rejected_cycle,
                opportunity=rejected_rows[0],
                outcome_state=SYSTEM_FAILURE,
                observed_at=CUTOFF,
                reason_codes=("UPSTREAM_UNAVAILABLE",),
            )

    def test_historical_session_cannot_enter_activated_prospective_sample(self):
        policy = DenominatorPolicy(
            status="ACTIVE_PROSPECTIVE",
            activated_at="2026-08-15T00:00:00Z",
            first_eligible_session_date="2026-08-15",
        )
        with self.assertRaises(OpportunityDenominatorError):
            self.cycle(mode=PROSPECTIVE, policy=policy)

    def test_inactive_sample_rejects_prospective_admission(self):
        with self.assertRaisesRegex(OpportunityDenominatorError, "not activated"):
            self.cycle(mode=PROSPECTIVE)

    def test_policy_sample_and_execution_authority_drift_rejected(self):
        with self.assertRaisesRegex(OpportunityDenominatorError, "Policy fingerprint drift"):
            self.cycle(policy=replace(current_policy(), policy_fingerprint=h("drift")))
        with self.assertRaisesRegex(OpportunityDenominatorError, "Sample identity"):
            self.cycle(policy=replace(current_policy(), sample_identity="other-sample"))
        with self.assertRaisesRegex(OpportunityDenominatorError, "execution authority"):
            self.cycle(policy=replace(current_policy(), execution_authority="ORDER_ALLOWED"))

    def test_malformed_record_fingerprint_and_authority_rejected(self):
        cycle, rows = self.cycle()
        with self.assertRaisesRegex(OpportunityDenominatorError, "fingerprint"):
            validate_cycle(replace(cycle, fingerprint="bad"))
        with self.assertRaisesRegex(OpportunityDenominatorError, "execution authority"):
            validate_opportunity(replace(rows[0], execution_authority="ORDER_ALLOWED"))

    def test_write_once_idempotency_conflict_restart_and_attachment_replay(self):
        cycle, rows = self.cycle()
        attachment = build_specialist_attachment(
            opportunity=rows[0],
            opinion=self.opinion(rows[0]),
            opinion_symbol="NVDA",
            attached_at=CUTOFF,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = OpportunityDenominatorStore(root)
            first.persist_cycle(cycle, rows)
            first.persist_cycle(cycle, rows)
            first.persist_attachment(attachment)
            first.persist_attachment(attachment)
            restarted = OpportunityDenominatorStore(root)
            summary = restarted.summary()
            self.assertEqual(1, summary.synthetic_cycles)
            self.assertEqual(0, summary.total_opportunities)
            self.assertEqual({"REGIME": 1}, summary.specialist_attachments_by_type)
            changed = replace(rows[0], blocker_reasons=("CHANGED",))
            changed_payload = {**changed.__dict__, "fingerprint": ""}
            from momentum_hunter import opportunity_denominator as module
            changed = replace(changed, fingerprint=module._record_fingerprint(module._to_wire_value(changed_payload)))
            with self.assertRaises(OpportunityDenominatorError):
                first.persist_cycle(cycle, [changed])

    def test_attachment_and_outcome_require_persisted_base_record(self):
        cycle, rows = self.cycle()
        attachment = build_specialist_attachment(
            opportunity=rows[0],
            opinion=self.opinion(rows[0]),
            opinion_symbol="NVDA",
            attached_at=CUTOFF,
        )
        market = build_market_path_outcome(
            opportunity=rows[0],
            bars=[self.bar(36, high=100, low=99)],
            entry_price=101,
            stop_price=98,
            target_price=103,
            horizon_end="2026-08-14T13:36:00Z",
            observation_class=ACTUAL_SYSTEM_DECISION,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = OpportunityDenominatorStore(Path(directory))
            with self.assertRaises(OpportunityDenominatorError):
                store.persist_attachment(attachment)
            with self.assertRaises(OpportunityDenominatorError):
                store.persist_outcome(market)
            store.persist_cycle(cycle, rows)
            store.persist_attachment(attachment)
            store.persist_outcome(market)
            self.assertEqual(1, len(list((store.sample_root / "outcomes").glob("*.json"))))

    def test_tampered_persisted_record_and_duplicate_json_keys_fail_closed(self):
        cycle, rows = self.cycle()
        with tempfile.TemporaryDirectory() as directory:
            store = OpportunityDenominatorStore(Path(directory))
            store.persist_cycle(cycle, rows)
            path = store._path("opportunities", rows[0].opportunity_id)
            payload = json.loads(path.read_text(encoding="ascii"))
            payload["payload"]["symbol"] = "MSFT"
            path.write_text(json.dumps(payload), encoding="ascii")
            with self.assertRaisesRegex(OpportunityDenominatorError, "fingerprint"):
                store.summary()
        with tempfile.TemporaryDirectory() as directory:
            store = OpportunityDenominatorStore(Path(directory))
            path = store._path("cycles", h("duplicate"))
            path.parent.mkdir(parents=True)
            path.write_text('{"recordType":"CYCLE","recordType":"CYCLE","payload":{}}', encoding="ascii")
            with self.assertRaisesRegex(OpportunityDenominatorError, "Malformed"):
                store.summary()

    def test_partial_temp_write_does_not_count_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = OpportunityDenominatorStore(root)
            folder = store.sample_root / "cycles"
            folder.mkdir(parents=True)
            (folder / ".partial.json.tmp").write_text("{", encoding="ascii")
            summary = OpportunityDenominatorStore(root).summary()
            self.assertEqual(0, summary.prospective_sessions)
            self.assertEqual(0, summary.total_opportunities)

    def test_opening_adapter_preserves_rows_but_marks_incomplete_and_does_not_mutate(self):
        report = {
            "metadata": {
                "generated_at": BASE_TIME,
                "source_session": "opening",
            },
            "candidates": [
                {
                    "rank": 1,
                    "symbol": "NVDA",
                    "trade_plan": {
                        "blocking_reasons": ["entry_not_triggered"],
                        "setup_evidence": {"fingerprint": h("setup")},
                        "intraday_evidence": {"plan_id": h("plan")},
                    },
                },
                {
                    "rank": 2,
                    "symbol": "SHOP",
                    "trade_plan": {"blocking_reasons": ["blocked_data"]},
                },
            ],
        }
        original = json.dumps(report, sort_keys=True)
        cycle, rows = adapt_opening_report(
            report=report,
            source_identity="opening-report:test",
            source_evidence_fingerprint=h("report"),
            raw_count=20,
            parsed_count=20,
        )
        self.assertEqual(original, json.dumps(report, sort_keys=True))
        self.assertEqual(RETROSPECTIVE_RESEARCH_EXAMPLE, cycle.observation_mode)
        self.assertFalse(cycle.complete_denominator)
        self.assertEqual(DENOMINATOR_INCOMPLETE, cycle.failure_reason)
        self.assertEqual(2, len(rows))
        self.assertEqual((MOMENTUM_CANDIDATE, RANK_ALTERNATIVE), rows[1].origin_kinds)
        self.assertTrue(all(row.disposition == NO_ACTION_RESEARCH_ONLY for row in rows))

    def test_summary_counts_only_prospective_opportunities_and_never_profitability(self):
        policy = DenominatorPolicy(
            status="ACTIVE_PROSPECTIVE",
            activated_at="2026-08-14T12:00:00Z",
            first_eligible_session_date="2026-08-14",
        )
        cycle, rows = self.cycle(mode=PROSPECTIVE, policy=policy)
        with tempfile.TemporaryDirectory() as directory:
            store = OpportunityDenominatorStore(Path(directory), policy=policy)
            store.persist_cycle(cycle, rows)
            summary = store.summary()
            self.assertEqual(1, summary.prospective_sessions)
            self.assertEqual(1, summary.total_opportunities)
            self.assertEqual(1, summary.selected)
            self.assertNotIn("win", summary.__dict__)
            self.assertNotIn("profit", summary.__dict__)


if __name__ == "__main__":
    unittest.main()
