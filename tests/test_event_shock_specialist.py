from __future__ import annotations

import ast
import copy
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.catalyst_evidence import (
    CatalystEvidenceCoordinator,
    CatalystEvidencePolicy,
    CatalystEvidenceStore,
    CatalystObservation,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_BLOCKED,
    CATALYST_SCORE_SUPPORTED,
    CUSTOMER_SUPPLIER,
    DIRECT_ISSUER,
    MACRO as CATALYST_MACRO,
    PEER,
    SECTOR as CATALYST_SECTOR,
    UNRESOLVED as CATALYST_UNRESOLVED,
)
from momentum_hunter.event_shock_specialist import (
    APPROVED_OTHER_SHOCK,
    COMMODITY,
    COMPETITOR,
    CYBER_INCIDENT,
    DATA_FAILURE,
    DIRECT_RELEVANCE,
    EVENT_CATEGORIES,
    EVENT_SHOCK_SPECIALIST_VERSION,
    EXPECTED_DOWN,
    EXPECTED_NON_DIRECTIONAL,
    EXPECTED_UP,
    GEOPOLITICAL_ESCALATION,
    IMMEDIATE_BREAKOUT_FAILURE,
    INDUSTRIAL_INCIDENT,
    MARKET_CONFIRMED_BEARISH,
    MARKET_CONFIRMED_BULLISH,
    MATERIAL_CORPORATE_EVENT,
    NEWS_PRICE_DISAGREEMENT,
    NO_MATERIAL_REACTION,
    RELATIVE_LAG,
    RESEARCH_HEURISTIC,
    SECTOR,
    SUPPLIER_CUSTOMER,
    SUPPLY_DISRUPTION,
    UNEXPECTED_REGULATION,
    UNRESOLVED,
    VOLUME_WITHOUT_PROGRESS,
    VOLATILITY_REACTION_CONFIRMED,
    EventShockResearchError,
    attach_actual_reaction,
    build_event_shock_classification,
    build_research_record,
    default_event_shock_policy,
    evaluate_event_shock_specialist,
    packet_json_bytes,
    research_record_json_bytes,
    validate_packet,
    validate_research_record,
)
from momentum_hunter.macro_event_context import (
    BLOCK_NEW_ENTRY,
    CURRENT,
    FED_DECISION,
    HIGH,
    MARKET,
    EventConsequenceRule,
    EventDefinition,
    EventRiskPolicy,
    EventRiskTarget,
    build_event_calendar,
    evaluate_event_risk,
)
from momentum_hunter.rolling_market_regime import RegimeBar
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BEARISH,
    BULLISH,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    FAILED,
    HEURISTIC,
    NO_DIRECTION,
    RESEARCH_ONLY,
    UNCALIBRATED,
    build_evidence_reference,
)


UTC = timezone.utc
CLASSIFIED_AT = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
INITIAL_AT = CLASSIFIED_AT + timedelta(minutes=3, seconds=5)
OPPORTUNITY_ID = "a" * 64


class EventShockSpecialistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_event_shock_policy()

    def evaluate(
        self,
        *,
        target_post=(100.10, 100.20, 100.35),
        benchmark_post=(100.01, 100.02, 100.04),
        target_volumes=None,
        expected_direction=EXPECTED_UP,
        relationship=DIRECT_ISSUER,
        score_authority=CATALYST_SCORE_SUPPORTED,
        breakout_level=None,
        macro_context=None,
        evaluated_at=INITIAL_AT,
    ):
        catalyst = make_catalyst(
            relationship=relationship,
            score_authority=score_authority,
        )
        classification = make_classification(
            catalyst,
            expected_direction=expected_direction,
            breakout_level=breakout_level,
        )
        target = bars(
            "NVDA",
            target_post,
            post_volumes=target_volumes,
        )
        benchmark = bars("SPY", benchmark_post)
        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=evaluated_at,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            macro_context=macro_context,
            policy=self.policy,
        )
        return catalyst, classification, target, benchmark, packet

    def test_bullish_market_confirmation_is_research_only(self) -> None:
        _, _, _, _, packet = self.evaluate()

        self.assertEqual(DIRECT_RELEVANCE, packet.relevance.relevance_state)
        self.assertEqual(MARKET_CONFIRMED_BULLISH, packet.confirmation.reaction_state)
        self.assertEqual(EVALUATED, packet.opinion.evaluation_status)
        self.assertEqual(BULLISH, packet.opinion.directional_bias)
        self.assertEqual(RESEARCH_ONLY, packet.opinion.authority)
        self.assertEqual(
            EXECUTION_AUTHORITY_NONE,
            packet.opinion.execution_authority,
        )
        self.assertFalse(packet.relevance.can_initiate_trade)
        self.assertFalse(packet.hypothesis.can_initiate_trade)
        self.assertFalse(packet.confirmation.can_initiate_trade)
        self.assertEqual(HEURISTIC, packet.opinion.confidence.kind)
        self.assertEqual(UNCALIBRATED, packet.opinion.confidence.calibration_status)

    def test_bearish_market_confirmation(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(99.90, 99.75, 99.60),
            benchmark_post=(99.99, 99.96, 99.90),
            expected_direction=EXPECTED_DOWN,
        )

        self.assertEqual(MARKET_CONFIRMED_BEARISH, packet.confirmation.reaction_state)
        self.assertEqual(BEARISH, packet.opinion.directional_bias)

    def test_non_directional_shock_requires_price_and_volume_confirmation(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(100.10, 100.22, 100.31),
            target_volumes=(2_000, 2_000, 2_000),
            expected_direction=EXPECTED_NON_DIRECTIONAL,
        )

        self.assertEqual(
            VOLATILITY_REACTION_CONFIRMED,
            packet.confirmation.reaction_state,
        )

    def test_news_price_disagreement_is_not_expected_reaction(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(99.95, 99.82, 99.70),
        )

        self.assertEqual(NEWS_PRICE_DISAGREEMENT, packet.confirmation.reaction_state)
        self.assertEqual(EXPECTED_UP, packet.hypothesis.expected_direction)
        self.assertEqual(BEARISH, packet.opinion.directional_bias)

    def test_volume_without_progress_is_separate_from_confirmation(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(100.02, 100.03, 100.04),
            target_volumes=(2_000, 2_000, 2_000),
        )

        self.assertEqual(VOLUME_WITHOUT_PROGRESS, packet.confirmation.reaction_state)

    def test_relative_lag_is_explicit(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(100.03, 100.04, 100.05),
            benchmark_post=(100.20, 100.30, 100.40),
        )

        self.assertEqual(RELATIVE_LAG, packet.confirmation.reaction_state)

    def test_immediate_breakout_failure_is_detected(self) -> None:
        catalyst = make_catalyst()
        classification = make_classification(catalyst, breakout_level=100.20)
        target = bars(
            "NVDA",
            (100.25, 100.10, 100.08),
            post_highs=(100.30, 100.26, 100.14),
        )
        benchmark = bars("SPY", (100.01, 100.02, 100.03))

        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(
            IMMEDIATE_BREAKOUT_FAILURE,
            packet.confirmation.reaction_state,
        )
        self.assertTrue(packet.confirmation.metrics.breakout_crossed)
        self.assertTrue(packet.confirmation.metrics.breakout_failed)
        self.assertTrue(packet.confirmation.metrics.immediate_breakout_failure)

    def test_all_roadmap_event_categories_are_versioned_and_deterministic(self) -> None:
        catalyst = make_catalyst()
        expected = {
            SUPPLY_DISRUPTION,
            INDUSTRIAL_INCIDENT,
            GEOPOLITICAL_ESCALATION,
            CYBER_INCIDENT,
            UNEXPECTED_REGULATION,
            MATERIAL_CORPORATE_EVENT,
            APPROVED_OTHER_SHOCK,
        }
        self.assertEqual(expected, EVENT_CATEGORIES)

        for category in sorted(expected):
            with self.subTest(category=category):
                first = make_classification(catalyst, category=category)
                second = make_classification(catalyst, category=category)
                self.assertEqual(first, second)
                self.assertEqual(category, first.category)

    def test_existing_relationship_semantics_map_without_reinterpretation(self) -> None:
        cases = (
            (DIRECT_ISSUER, CATALYST_SCORE_SUPPORTED, DIRECT_ISSUER),
            (PEER, CATALYST_SCORE_SUPPORTED, COMPETITOR),
            (CUSTOMER_SUPPLIER, CATALYST_SCORE_SUPPORTED, SUPPLIER_CUSTOMER),
            (CATALYST_SECTOR, CATALYST_SCORE_SUPPORTED, SECTOR),
            (CATALYST_MACRO, CATALYST_SCORE_SUPPORTED, "MACRO"),
            (CATALYST_UNRESOLVED, CATALYST_SCORE_BLOCKED, UNRESOLVED),
        )

        for source, authority, expected in cases:
            with self.subTest(source=source):
                catalyst = make_catalyst(
                    relationship=source,
                    score_authority=authority,
                )
                classification = make_classification(catalyst)
                self.assertEqual(expected, classification.relationship_type)

    def test_commodity_relationship_requires_separate_provenance(self) -> None:
        catalyst = make_catalyst(relationship=CATALYST_MACRO)
        relationship_ref = build_evidence_reference(
            evidence_id="commodity-map-nvda-v1",
            evidence_type="COMMODITY_RELATIONSHIP",
            source="approved-commodity-map-v1",
            as_of=CLASSIFIED_AT - timedelta(seconds=1),
            fingerprint="b" * 64,
        )

        with self.assertRaisesRegex(EventShockResearchError, "supplemental"):
            make_classification(catalyst, relationship_type=COMMODITY)

        classification = make_classification(
            catalyst,
            relationship_type=COMMODITY,
            supplemental_relationship_evidence=relationship_ref,
        )
        self.assertEqual(COMMODITY, classification.relationship_type)

    def test_unresolved_relationship_abstains_and_cannot_look_neutral(self) -> None:
        _, _, _, _, packet = self.evaluate(
            relationship=CATALYST_UNRESOLVED,
            score_authority=CATALYST_SCORE_BLOCKED,
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual(NO_DIRECTION, packet.opinion.directional_bias)
        self.assertIsNone(packet.hypothesis)

    def test_stale_catalyst_abstains(self) -> None:
        catalyst = make_catalyst(published_at=CLASSIFIED_AT - timedelta(minutes=10))
        classification = make_classification(catalyst)
        target = bars("NVDA", (100.1, 100.2, 100.3))
        benchmark = bars("SPY", (100.01, 100.02, 100.03))

        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("STALE_EVIDENCE", packet.opinion.abstention_reason)

    def test_headline_without_market_evidence_abstains(self) -> None:
        catalyst = make_catalyst()
        classification = make_classification(catalyst)

        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=(),
            benchmark_bars=(),
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("INSUFFICIENT_EVIDENCE", packet.opinion.abstention_reason)
        self.assertIsNone(packet.hypothesis)

    def test_missing_confirmation_abstains_but_preserves_prospective_hypothesis(self) -> None:
        catalyst = make_catalyst()
        classification = make_classification(catalyst)
        target = bars("NVDA", (100.1,))
        benchmark = bars("SPY", (100.01,))

        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=CLASSIFIED_AT + timedelta(minutes=1, seconds=5),
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertIsNotNone(packet.hypothesis)

    def test_macro_context_is_reused_as_disclosed_evidence_only(self) -> None:
        context = macro_context(OPPORTUNITY_ID, INITIAL_AT)
        _, _, _, _, packet = self.evaluate(macro_context=context)

        self.assertIn("MARKET_REGIME", packet.opinion.feature_families)
        self.assertTrue(
            any(
                item.evidence_type == "MACRO_EVENT_CONTEXT"
                for item in packet.opinion.evidence_refs
            )
        )
        self.assertEqual(RESEARCH_ONLY, packet.opinion.authority)

    def test_actual_reaction_attaches_without_rewriting_hypothesis(self) -> None:
        catalyst, classification, initial_target, initial_benchmark, packet = self.evaluate()
        original_packet_bytes = packet_json_bytes(packet)
        record = build_research_record(packet)
        target = bars(
            "NVDA",
            tuple(100.10 + index * 0.07 for index in range(15)),
        )
        benchmark = bars(
            "SPY",
            tuple(100.01 + index * 0.01 for index in range(15)),
        )

        completed = attach_actual_reaction(
            record,
            target_bars=target,
            benchmark_bars=benchmark,
            observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
        )
        duplicate = attach_actual_reaction(
            completed,
            target_bars=target,
            benchmark_bars=benchmark,
            observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
        )

        self.assertEqual(original_packet_bytes, packet_json_bytes(completed.packet))
        self.assertEqual(packet.hypothesis, completed.packet.hypothesis)
        self.assertEqual(MARKET_CONFIRMED_BULLISH, completed.actual_reaction.reaction_state)
        self.assertEqual(completed, duplicate)
        self.assertNotEqual(record.fingerprint, completed.fingerprint)
        self.assertEqual(catalyst, catalyst)
        self.assertEqual(classification, classification)
        self.assertEqual(initial_target, initial_target)
        self.assertEqual(initial_benchmark, initial_benchmark)

    def test_conflicting_actual_reaction_cannot_replace_write_once_result(self) -> None:
        _, _, _, _, packet = self.evaluate()
        record = build_research_record(packet)
        target = bars("NVDA", tuple(100.1 + index * 0.05 for index in range(15)))
        benchmark = bars("SPY", tuple(100.01 + index * 0.01 for index in range(15)))
        completed = attach_actual_reaction(
            record,
            target_bars=target,
            benchmark_bars=benchmark,
            observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
        )
        different = bars("NVDA", tuple(100.1 - index * 0.05 for index in range(15)))

        with self.assertRaisesRegex(EventShockResearchError, "write-once"):
            attach_actual_reaction(
                completed,
                target_bars=different,
                benchmark_bars=benchmark,
                observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
            )

    def test_incomplete_actual_window_is_data_failure_not_fabricated_outcome(self) -> None:
        _, _, _, _, packet = self.evaluate()
        record = build_research_record(packet)
        target = bars("NVDA", tuple(100.1 + index * 0.03 for index in range(10)))
        benchmark = bars("SPY", tuple(100.01 + index * 0.01 for index in range(10)))

        completed = attach_actual_reaction(
            record,
            target_bars=target,
            benchmark_bars=benchmark,
            observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
        )

        self.assertEqual(DATA_FAILURE, completed.actual_reaction.reaction_state)
        self.assertIsNone(completed.actual_reaction.metrics)

    def test_completed_quiet_horizon_is_no_material_reaction(self) -> None:
        _, _, _, _, packet = self.evaluate(
            target_post=(100.01, 100.02, 100.03),
            benchmark_post=(100.01, 100.01, 100.02),
        )
        record = build_research_record(packet)
        target = bars("NVDA", tuple(100.01 + index * 0.002 for index in range(15)))
        benchmark = bars("SPY", tuple(100.01 + index * 0.001 for index in range(15)))

        completed = attach_actual_reaction(
            record,
            target_bars=target,
            benchmark_bars=benchmark,
            observed_at=CLASSIFIED_AT + timedelta(minutes=15, seconds=5),
        )

        self.assertEqual(NO_MATERIAL_REACTION, completed.actual_reaction.reaction_state)

    def test_future_bar_fails_closed(self) -> None:
        catalyst = make_catalyst()
        classification = make_classification(catalyst)
        target = bars("NVDA", (100.1, 100.2, 100.3, 100.4))
        benchmark = bars("SPY", (100.01, 100.02, 100.03, 100.04))

        packet = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertEqual("MARKET_EVIDENCE_INVALID", packet.opinion.failure_reason)

    def test_tampering_is_detected(self) -> None:
        _, _, _, _, packet = self.evaluate()

        with self.assertRaisesRegex(EventShockResearchError, "identity|fingerprint"):
            validate_packet(
                replace(
                    packet,
                    relevance=replace(packet.relevance, relationship_type=COMPETITOR),
                )
            )

    def test_deterministic_byte_stable_and_input_nonmutating(self) -> None:
        catalyst = make_catalyst()
        classification = make_classification(catalyst)
        target = list(bars("NVDA", (100.1, 100.2, 100.35)))
        benchmark = list(bars("SPY", (100.01, 100.02, 100.04)))
        before_target = copy.deepcopy(target)
        before_benchmark = copy.deepcopy(benchmark)

        first = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=target,
            benchmark_bars=benchmark,
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )
        second = evaluate_event_shock_specialist(
            catalyst=catalyst,
            classification=classification,
            target_bars=tuple(target),
            benchmark_bars=tuple(benchmark),
            evaluated_at=INITIAL_AT,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id="candidate-nvda",
            policy=self.policy,
        )

        self.assertEqual(first, second)
        self.assertEqual(packet_json_bytes(first), packet_json_bytes(second))
        self.assertEqual(before_target, target)
        self.assertEqual(before_benchmark, benchmark)
        with self.assertRaises(FrozenInstanceError):
            first.relevance.relevance_state = "CHANGED"  # type: ignore[misc]

    def test_research_record_serialization_and_validation_are_stable(self) -> None:
        _, _, _, _, packet = self.evaluate()
        record = build_research_record(packet)

        validate_research_record(record)
        self.assertEqual(
            research_record_json_bytes(record),
            research_record_json_bytes(build_research_record(packet)),
        )

    def test_policy_identity_and_threshold_semantics_are_explicit(self) -> None:
        self.assertEqual(EVENT_SHOCK_SPECIALIST_VERSION, self.policy.specialist_version)
        self.assertEqual(RESEARCH_HEURISTIC, self.policy.threshold_semantics)
        self.assertEqual((5, 15, 30, 60), self.policy.supported_horizons_minutes)

    def test_module_has_no_provider_network_runtime_or_execution_import(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "event_shock_specialist.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        forbidden = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "schwab",
            "broker",
            "order",
            "service",
            "scheduler",
            "engine_host",
            "shadow",
            "trade_plan",
            "risk_governor",
        )
        for name in imports:
            self.assertFalse(
                any(token in name.lower() for token in forbidden),
                name,
            )


def make_catalyst(
    *,
    relationship: str = DIRECT_ISSUER,
    score_authority: str = CATALYST_SCORE_SUPPORTED,
    published_at: datetime | None = None,
):
    published = published_at or CLASSIFIED_AT - timedelta(seconds=60)
    policy = CatalystEvidencePolicy(
        policy_version="synthetic-event-catalyst-policy-v1",
        maximum_age_seconds=300,
        future_tolerance_seconds=5,
        material_delta_profile="synthetic-event-material-delta-v1",
    )
    with tempfile.TemporaryDirectory() as directory:
        coordinator = CatalystEvidenceCoordinator(
            CatalystEvidenceStore(Path(directory) / "catalyst.json"),
            policy=policy,
        )
        result = coordinator.observe(
            CatalystObservation(
                source_identity="synthetic-event-wire-v1",
                source_article_id=f"event-{relationship.lower()}",
                provider="synthetic-provider",
                source_name="Synthetic Event Wire",
                candidate_symbol="NVDA",
                candidate_company="NVIDIA Corp",
                headline="Synthetic material event affects NVDA",
                summary="Synthetic evidence for deterministic testing only.",
                published_at=iso(published),
                provider_timestamp=iso(published + timedelta(seconds=1)),
                receipt_timestamp=iso(published + timedelta(seconds=2)),
                relationship_type=relationship,
                relationship_evidence="Explicit synthetic relationship evidence.",
                score_authority=score_authority,
                canonical_url="https://example.invalid/event",
                mentioned_symbol="NVDA" if relationship == DIRECT_ISSUER else "",
                mentioned_company="NVIDIA Corp" if relationship == DIRECT_ISSUER else "",
            )
        )
        return coordinator.snapshot(
            result.revision.event_id,
            evaluated_at=CLASSIFIED_AT,
        )


def make_classification(
    catalyst,
    *,
    category: str = MATERIAL_CORPORATE_EVENT,
    expected_direction: str = EXPECTED_UP,
    breakout_level: float | None = None,
    relationship_type: str | None = None,
    supplemental_relationship_evidence=None,
):
    return build_event_shock_classification(
        catalyst=catalyst,
        category=category,
        expected_direction=expected_direction,
        benchmark_symbol="SPY",
        classified_at=CLASSIFIED_AT,
        expected_horizon_minutes=15,
        breakout_level=breakout_level,
        relationship_type=relationship_type,
        supplemental_relationship_evidence=supplemental_relationship_evidence,
    )


def bars(
    symbol: str,
    post_closes,
    *,
    post_volumes=None,
    post_highs=None,
    post_lows=None,
    baseline_count: int = 20,
):
    result = []
    previous = 100.0
    start = CLASSIFIED_AT - timedelta(minutes=baseline_count)
    for index in range(baseline_count):
        result.append(
            RegimeBar(
                symbol=symbol,
                timestamp=iso(start + timedelta(minutes=index)),
                open=previous,
                high=previous + 0.02,
                low=previous - 0.02,
                close=previous,
                volume=1_000.0,
                source_identity=f"synthetic-{symbol.lower()}-canonical-v1",
                source_state="RECONCILED",
            )
        )
    volumes = post_volumes or tuple(1_200.0 for _ in post_closes)
    for index, close in enumerate(post_closes):
        high = post_highs[index] if post_highs else max(previous, close) + 0.02
        low = post_lows[index] if post_lows else min(previous, close) - 0.02
        result.append(
            RegimeBar(
                symbol=symbol,
                timestamp=iso(CLASSIFIED_AT + timedelta(minutes=index)),
                open=previous,
                high=high,
                low=low,
                close=float(close),
                volume=float(volumes[index]),
                source_identity=f"synthetic-{symbol.lower()}-canonical-v1",
                source_state="RECONCILED",
            )
        )
        previous = float(close)
    return tuple(result)


def macro_context(target: str, evaluated_at: datetime):
    definition = EventDefinition(
        source_event_id="fed-event-1",
        revision_identity="revision-1",
        category=FED_DECISION,
        title="Synthetic Fed event",
        importance=HIGH,
        evidence_state=CURRENT,
        scheduled_start=iso(evaluated_at - timedelta(minutes=5)),
        scheduled_end=iso(evaluated_at + timedelta(minutes=5)),
        risk_window_start=iso(evaluated_at - timedelta(minutes=15)),
        risk_window_end=iso(evaluated_at + timedelta(minutes=15)),
        observation_window_start=iso(evaluated_at - timedelta(minutes=30)),
        observation_window_end=iso(evaluated_at + timedelta(minutes=30)),
        scope=MARKET,
        source_identity="synthetic-approved-calendar",
        provider_timestamp=iso(evaluated_at - timedelta(hours=1)),
        receipt_timestamp=iso(evaluated_at - timedelta(minutes=59)),
    )
    calendar = build_event_calendar(
        definitions=(definition,),
        generated_at=evaluated_at - timedelta(minutes=50),
        valid_through=evaluated_at + timedelta(hours=1),
    )
    policy = EventRiskPolicy(
        policy_version="synthetic-event-macro-policy-v1",
        rules=(EventConsequenceRule(FED_DECISION, HIGH, BLOCK_NEW_ENTRY),),
        maximum_candidate_fan_out=3,
    )
    return evaluate_event_risk(
        calendar=calendar,
        policy=policy,
        evaluated_at=evaluated_at,
        target=EventRiskTarget(target, "NVDA"),
    )


def iso(value: datetime) -> str:
    return value.isoformat()


if __name__ == "__main__":
    unittest.main()
