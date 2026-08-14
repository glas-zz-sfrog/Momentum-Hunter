from __future__ import annotations

import ast
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    expected_opportunity_id,
    expected_setup_id,
)
from momentum_hunter.intraday_trade_plan import (
    OPENING_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BULLISH,
    CALIBRATED,
    CALIBRATED_PROBABILITY,
    CONTRACT_VERSION,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    FAILED,
    HEURISTIC,
    NEUTRAL,
    NO_DIRECTION,
    NO_OPINION,
    RESEARCH_ONLY,
    UNCALIBRATED,
    ConfidenceMetadata,
    EvidenceReference,
    SpecialistOpinionError,
    build_confidence,
    build_evidence_reference,
    build_specialist_opinion,
    expected_opinion_id,
    input_evidence_fingerprint,
    opinion_from_json,
    opinion_from_wire,
    opinion_is_expired,
    opinion_json_bytes,
    opinion_to_wire,
    specialist_opinion_fingerprint,
    unavailable_confidence,
    validate_confidence,
    validate_evidence_reference,
    validate_opinion_target_identity,
    validate_specialist_opinion,
)


AS_OF = datetime(2026, 8, 17, 14, 35, tzinfo=timezone.utc)
EXPIRES_AT = AS_OF + timedelta(minutes=15)
OPPORTUNITY_ID = "1" * 64
CANDIDATE_ID = "candidate-specialist-contract-1"
SETUP_ID = "2" * 64
TRADE_PLAN_ID = "3" * 64
POLICY_FINGERPRINT = "4" * 64


class SpecialistOpinionTests(unittest.TestCase):
    def test_reference_regime_opinion_is_research_only_and_neutral(self) -> None:
        opinion = evaluated_opinion(
            specialist_id="REGIME",
            specialist_version="regime-v1",
            opinion_code="LATE_TREND",
            directional_bias=NEUTRAL,
            feature_families=("MARKET_REGIME",),
            reason_codes=("BENCHMARK_TREND_MATURE",),
        )

        self.assertEqual(EVALUATED, opinion.evaluation_status)
        self.assertEqual("LATE_TREND", opinion.opinion_code)
        self.assertEqual(NEUTRAL, opinion.directional_bias)
        self.assertEqual(RESEARCH_ONLY, opinion.authority)
        self.assertEqual(EXECUTION_AUTHORITY_NONE, opinion.execution_authority)

    def test_reference_technical_structure_opinion_is_bullish(self) -> None:
        opinion = evaluated_opinion()

        self.assertEqual("TECHNICAL_STRUCTURE", opinion.specialist_id)
        self.assertEqual("STRUCTURE_SUPPORTS", opinion.opinion_code)
        self.assertEqual(BULLISH, opinion.directional_bias)
        self.assertEqual(("CANDLE_STRUCTURE",), opinion.feature_families)

    def test_reference_statistical_outcome_has_calibrated_probability(self) -> None:
        confidence = build_confidence(
            value=0.62,
            kind=CALIBRATED_PROBABILITY,
            calibration_status=CALIBRATED,
            sample_size=250,
            model_version="outcome-calibration-v1",
        )
        opinion = evaluated_opinion(
            specialist_id="STATISTICAL_OUTCOME",
            specialist_version="statistical-outcome-v1",
            opinion_code="POSITIVE_EXPECTANCY",
            directional_bias=BULLISH,
            feature_families=("HISTORICAL_ANALOGS",),
            reason_codes=("CALIBRATED_SAMPLE_POSITIVE",),
            confidence=confidence,
        )

        self.assertTrue(opinion.confidence.available)
        self.assertEqual(0.62, opinion.confidence.value)
        self.assertEqual(CALIBRATED_PROBABILITY, opinion.confidence.kind)
        self.assertEqual(250, opinion.confidence.sample_size)

    def test_reference_event_shock_abstains_for_insufficient_evidence(self) -> None:
        opinion = build_specialist_opinion(
            specialist_id="EVENT_SHOCK",
            specialist_version="event-shock-v1",
            opportunity_id=OPPORTUNITY_ID,
            candidate_id=CANDIDATE_ID,
            setup_id=SETUP_ID,
            trade_plan_id=TRADE_PLAN_ID,
            as_of=AS_OF,
            expires_at=EXPIRES_AT,
            research_identity="synthetic-specialist-contract-fixtures-v1",
            policy_fingerprint=POLICY_FINGERPRINT,
            evaluation_status=ABSTAINED,
            opinion_code=NO_OPINION,
            directional_bias=NO_DIRECTION,
            abstention_reason="INSUFFICIENT_EVIDENCE",
            reason_codes=("CATALYST_EVIDENCE_MISSING",),
        )

        self.assertEqual(ABSTAINED, opinion.evaluation_status)
        self.assertEqual(NO_OPINION, opinion.opinion_code)
        self.assertEqual("INSUFFICIENT_EVIDENCE", opinion.abstention_reason)
        self.assertFalse(opinion.confidence.available)

    def test_multiple_specialists_interoperate_without_an_arbiter(self) -> None:
        opinions = (
            evaluated_opinion(),
            evaluated_opinion(
                specialist_id="REGIME",
                specialist_version="regime-v1",
                opinion_code="LATE_TREND",
                directional_bias=NEUTRAL,
                feature_families=("MARKET_REGIME",),
                reason_codes=("BENCHMARK_TREND_MATURE",),
            ),
        )

        self.assertEqual(2, len({item.opinion_id for item in opinions}))
        self.assertTrue(all(item.authority == RESEARCH_ONLY for item in opinions))
        import momentum_hunter.specialist_opinion as contract

        self.assertFalse(hasattr(contract, "aggregate_opinions"))
        self.assertFalse(hasattr(contract, "select_trade"))
        self.assertFalse(hasattr(contract, "veto_trade"))

    def test_deterministic_serialization_ignores_input_order(self) -> None:
        first = evidence_ref("evidence-b", "b" * 64, "VOLUME_PROFILE")
        second = evidence_ref("evidence-a", "a" * 64, "MINUTE_CANDLES")
        left = evaluated_opinion(
            evidence_refs=(first, second),
            feature_families=("VOLUME", "CANDLE_STRUCTURE"),
            reason_codes=("VOLUME_CONFIRMS", "STRUCTURE_HELD"),
        )
        right = evaluated_opinion(
            evidence_refs=(second, first),
            feature_families=("CANDLE_STRUCTURE", "VOLUME"),
            reason_codes=("STRUCTURE_HELD", "VOLUME_CONFIRMS"),
        )

        self.assertEqual(left, right)
        self.assertEqual(opinion_json_bytes(left), opinion_json_bytes(right))
        self.assertTrue(opinion_json_bytes(left).endswith(b"\n"))

    def test_json_round_trip_is_strict_and_byte_stable(self) -> None:
        original = evaluated_opinion()

        restored = opinion_from_json(opinion_json_bytes(original))

        self.assertEqual(original, restored)
        self.assertEqual(opinion_json_bytes(original), opinion_json_bytes(restored))
        self.assertEqual(CONTRACT_VERSION, restored.contract_version)

    def test_frozen_contract_rejects_mutation(self) -> None:
        opinion = evaluated_opinion()

        with self.assertRaises(FrozenInstanceError):
            opinion.opinion_code = "CHANGED"  # type: ignore[misc]

    def test_evidence_change_changes_input_identity_and_record_identity(self) -> None:
        original = evaluated_opinion()
        changed = evaluated_opinion(
            evidence_refs=(evidence_ref("evidence-1", "f" * 64),)
        )

        self.assertNotEqual(
            original.input_evidence_fingerprint,
            changed.input_evidence_fingerprint,
        )
        self.assertNotEqual(original.opinion_id, changed.opinion_id)
        self.assertNotEqual(original.fingerprint, changed.fingerprint)

    def test_specialist_version_and_opinion_code_change_identity(self) -> None:
        original = evaluated_opinion()
        new_version = evaluated_opinion(specialist_version="technical-structure-v2")
        new_code = evaluated_opinion(opinion_code="STRUCTURE_OPPOSES")

        self.assertNotEqual(original.opinion_id, new_version.opinion_id)
        self.assertNotEqual(original.opinion_id, new_code.opinion_id)

    def test_authority_is_identity_bound_but_v1_escalation_is_rejected(self) -> None:
        original = evaluated_opinion()
        elevated = replace(
            original,
            authority="EXECUTION_VETO",
            opinion_id="",
            fingerprint="",
        )

        elevated_id = expected_opinion_id(elevated)
        self.assertNotEqual(original.opinion_id, elevated_id)
        elevated = replace(elevated, opinion_id=elevated_id)
        elevated = replace(
            elevated,
            fingerprint=specialist_opinion_fingerprint(elevated),
        )
        with self.assertRaisesRegex(SpecialistOpinionError, "RESEARCH_ONLY"):
            validate_specialist_opinion(elevated)

    def test_wire_tampering_is_detected(self) -> None:
        payload = opinion_to_wire(evaluated_opinion())
        payload["directionalBias"] = "BEARISH"

        with self.assertRaisesRegex(SpecialistOpinionError, "identity is invalid"):
            opinion_from_wire(payload)

    def test_unknown_wire_field_is_rejected(self) -> None:
        payload = opinion_to_wire(evaluated_opinion())
        payload["universalScore"] = 99

        with self.assertRaisesRegex(SpecialistOpinionError, "wire fields"):
            opinion_from_wire(payload)

    def test_duplicate_json_object_keys_are_rejected(self) -> None:
        serialized = opinion_json_bytes(evaluated_opinion()).decode("ascii")
        duplicated = serialized.replace(
            '{"abstentionReason":null,',
            '{"abstentionReason":null,"abstentionReason":null,',
            1,
        )

        with self.assertRaisesRegex(SpecialistOpinionError, "duplicate object keys"):
            opinion_from_json(duplicated)

    def test_unsupported_contract_version_is_rejected(self) -> None:
        payload = opinion_to_wire(evaluated_opinion())
        payload["contractVersion"] = 2

        with self.assertRaisesRegex(SpecialistOpinionError, "version"):
            opinion_from_wire(payload)

    def test_missing_specialist_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "Specialist identity"):
            evaluated_opinion(specialist_id="")

    def test_malformed_specialist_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "Specialist version"):
            evaluated_opinion(specialist_version=2)

    def test_missing_direction_is_not_coerced_to_none(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "Directional bias"):
            evaluated_opinion(directional_bias=None)

    def test_malformed_opportunity_identity_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "Opportunity identity"):
            evaluated_opinion(opportunity_id="not-a-hash")

    def test_setup_requires_candidate_identity(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "requires candidate"):
            evaluated_opinion(candidate_id=None)

    def test_trade_plan_requires_setup_identity(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "requires setup"):
            evaluated_opinion(setup_id=None)

    def test_wrong_setup_target_identity_is_rejected(self) -> None:
        opinion = evaluated_opinion()

        validate_opinion_target_identity(
            opinion,
            opportunity_id=OPPORTUNITY_ID,
            candidate_id=CANDIDATE_ID,
            setup_id=SETUP_ID,
            trade_plan_id=TRADE_PLAN_ID,
        )
        with self.assertRaisesRegex(SpecialistOpinionError, "target identity"):
            validate_opinion_target_identity(
                opinion,
                opportunity_id=OPPORTUNITY_ID,
                candidate_id=CANDIDATE_ID,
                setup_id="9" * 64,
                trade_plan_id=TRADE_PLAN_ID,
            )

    def test_naive_as_of_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "UTC offset"):
            evaluated_opinion(as_of=datetime(2026, 8, 17, 14, 35))

    def test_naive_expiration_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "UTC offset"):
            evaluated_opinion(expires_at=datetime(2026, 8, 17, 14, 50))

    def test_nonpositive_lifetime_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "expires"):
            evaluated_opinion(expires_at=AS_OF)

    def test_future_evidence_is_rejected(self) -> None:
        reference = evidence_ref(
            "future-evidence",
            "a" * 64,
            as_of=AS_OF + timedelta(seconds=1),
        )

        with self.assertRaisesRegex(SpecialistOpinionError, "future evidence"):
            evaluated_opinion(evidence_refs=(reference,))

    def test_malformed_evidence_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "fingerprint"):
            build_evidence_reference(
                evidence_id="evidence-1",
                evidence_type="MINUTE_CANDLES",
                source="synthetic-fixture",
                as_of=AS_OF,
                fingerprint="bad",
            )

    def test_duplicate_evidence_identity_is_rejected(self) -> None:
        reference = evidence_ref("evidence-1", "a" * 64)

        with self.assertRaisesRegex(SpecialistOpinionError, "duplicated"):
            evaluated_opinion(evidence_refs=(reference, reference))

    def test_conflicting_evidence_identity_is_rejected(self) -> None:
        first = evidence_ref("evidence-1", "a" * 64)
        second = evidence_ref("evidence-1", "b" * 64)

        with self.assertRaisesRegex(SpecialistOpinionError, "contradictory"):
            evaluated_opinion(evidence_refs=(first, second))

    def test_execution_authority_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "execution authority"):
            evaluated_opinion(execution_authority="ORDER_AUTHORITY")

    def test_unknown_authority_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "RESEARCH_ONLY"):
            evaluated_opinion(authority="ADVISORY")

    def test_value_without_confidence_semantics_is_rejected(self) -> None:
        invalid = ConfidenceMetadata(
            available=True,
            value=0.75,
            kind="UNAVAILABLE",
            calibration_status="UNAVAILABLE",
            sample_size=None,
            model_version="confidence-v1",
        )

        with self.assertRaisesRegex(SpecialistOpinionError, "missing confidence"):
            validate_confidence(invalid)

    def test_probability_outside_unit_interval_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, r"outside \[0, 1\]"):
            build_confidence(
                value=1.2,
                kind=CALIBRATED_PROBABILITY,
                calibration_status=CALIBRATED,
                sample_size=100,
                model_version="probability-v1",
            )

    def test_uncalibrated_probability_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "calibrated semantics"):
            build_confidence(
                value=0.6,
                kind=CALIBRATED_PROBABILITY,
                calibration_status=UNCALIBRATED,
                sample_size=100,
                model_version="probability-v1",
            )

    def test_calibrated_heuristic_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "heuristic"):
            build_confidence(
                value=0.6,
                kind=HEURISTIC,
                calibration_status=CALIBRATED,
                sample_size=None,
                model_version="heuristic-v1",
            )

    def test_confidence_numeric_representation_is_canonical(self) -> None:
        integer_input = build_confidence(
            value=1,
            kind=HEURISTIC,
            calibration_status=UNCALIBRATED,
            sample_size=None,
            model_version="heuristic-v1",
        )
        float_input = build_confidence(
            value=1.0,
            kind=HEURISTIC,
            calibration_status=UNCALIBRATED,
            sample_size=None,
            model_version="heuristic-v1",
        )

        self.assertEqual(integer_input, float_input)
        self.assertIs(type(integer_input.value), float)

    def test_abstention_without_reason_is_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "Abstention reason"):
            build_specialist_opinion(
                **base_arguments(),
                evaluation_status=ABSTAINED,
                opinion_code=NO_OPINION,
                directional_bias=NO_DIRECTION,
            )

    def test_abstention_cannot_carry_actionable_opinion(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "NO_OPINION"):
            build_specialist_opinion(
                **base_arguments(),
                evaluation_status=ABSTAINED,
                opinion_code="STRUCTURE_SUPPORTS",
                directional_bias=NO_DIRECTION,
                abstention_reason="INSUFFICIENT_EVIDENCE",
            )

    def test_failed_evaluation_cannot_masquerade_as_neutral_opinion(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "cannot be neutral"):
            build_specialist_opinion(
                **base_arguments(),
                evaluation_status=FAILED,
                opinion_code=None,
                directional_bias=NEUTRAL,
                failure_reason="MODEL_RUNTIME_FAILURE",
            )

    def test_evaluated_opinion_requires_feature_family_disclosure(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "family disclosure"):
            evaluated_opinion(feature_families=())

    def test_expiration_is_explicit_and_boundary_inclusive(self) -> None:
        opinion = evaluated_opinion()

        self.assertFalse(
            opinion_is_expired(
                opinion,
                EXPIRES_AT - timedelta(microseconds=1),
            )
        )
        self.assertTrue(opinion_is_expired(opinion, EXPIRES_AT))

    def test_bare_string_collections_are_rejected(self) -> None:
        with self.assertRaisesRegex(SpecialistOpinionError, "token sequence"):
            evaluated_opinion(feature_families="CANDLE_STRUCTURE")
        with self.assertRaisesRegex(SpecialistOpinionError, "record sequence"):
            evaluated_opinion(evidence_refs="evidence-1")

    def test_direct_noncanonical_records_are_rejected(self) -> None:
        reference = EvidenceReference(
            evidence_id=" evidence-1 ",
            evidence_type="minute_candles",
            source="synthetic-fixture",
            as_of="2026-08-17T14:35:00Z",
            fingerprint="A" * 64,
        )

        with self.assertRaisesRegex(SpecialistOpinionError, "not canonical"):
            validate_evidence_reference(reference)

    def test_contract_accepts_real_mh_identity_builders(self) -> None:
        opportunity_id = expected_opportunity_id(
            "NVDA", "2026-08-17", "OPENING_BOOTSTRAP"
        )
        setup_id = expected_setup_id(opportunity_id, OPENING_BREAKOUT, 1)
        plan = build_intraday_plan_evidence(
            symbol="NVDA",
            setup_family=OPENING_BREAKOUT,
            created_at=datetime.fromisoformat("2026-08-17T09:35:00-04:00"),
            planned_entry=181.25,
            stop_price=178.50,
            target_prices=(184.0, 186.75),
            source_setup_fingerprint=setup_id,
            source_level_kind="COMPLETED_OPENING_RANGE_HIGH",
            source_evidence_ids=("canonical-candles-nvda-20260817",),
        )

        opinion = evaluated_opinion(
            opportunity_id=opportunity_id,
            setup_id=setup_id,
            trade_plan_id=plan.plan_id,
        )

        self.assertEqual(opportunity_id, opinion.opportunity_id)
        self.assertEqual(setup_id, opinion.setup_id)
        self.assertEqual(plan.plan_id, opinion.trade_plan_id)
        self.assertEqual(64, len(opinion.opinion_id))

    def test_reason_codes_remain_authoritative_over_bounded_narrative(self) -> None:
        opinion = evaluated_opinion(
            reason_codes=("BREAKOUT_LEVEL_HELD", "VOLUME_CONFIRMED"),
            explanation="Synthetic fixture narrative for a human reviewer.",
        )
        payload = opinion_to_wire(opinion)

        self.assertEqual(
            ["BREAKOUT_LEVEL_HELD", "VOLUME_CONFIRMED"],
            payload["reasonCodes"],
        )
        self.assertNotIn("score", {key.lower() for key in payload})

    def test_builder_does_not_mutate_caller_collections(self) -> None:
        references = [evidence_ref("evidence-b", "b" * 64)]
        families = ["CANDLE_STRUCTURE"]
        reasons = ["STRUCTURE_HELD"]
        original = (list(references), list(families), list(reasons))

        evaluated_opinion(
            evidence_refs=references,
            feature_families=families,
            reason_codes=reasons,
        )

        self.assertEqual(original, (references, families, reasons))

    def test_module_has_no_runtime_or_capability_imports(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "specialist_opinion.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        forbidden = {
            "requests",
            "urllib",
            "socket",
            "pathlib",
            "subprocess",
            "alpaca",
            "schwab",
            "broker",
            "execution",
            "trade_planning",
            "risk_governor",
            "successor_setup_observer",
        }

        self.assertFalse(imports & forbidden)

    def test_input_fingerprint_is_publicly_reproducible(self) -> None:
        references = (
            evidence_ref("evidence-a", "a" * 64),
            evidence_ref("evidence-b", "b" * 64),
        )
        opinion = evaluated_opinion(evidence_refs=references)

        self.assertEqual(
            input_evidence_fingerprint(references),
            opinion.input_evidence_fingerprint,
        )
        validate_specialist_opinion(opinion)


def evidence_ref(
    evidence_id: str = "evidence-1",
    fingerprint: str = "e" * 64,
    evidence_type: str = "MINUTE_CANDLES",
    *,
    as_of: datetime = AS_OF,
) -> EvidenceReference:
    return build_evidence_reference(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        source="synthetic-specialist-contract-fixture",
        as_of=as_of,
        fingerprint=fingerprint,
    )


def base_arguments(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "specialist_id": "TECHNICAL_STRUCTURE",
        "specialist_version": "technical-structure-v1",
        "opportunity_id": OPPORTUNITY_ID,
        "candidate_id": CANDIDATE_ID,
        "setup_id": SETUP_ID,
        "trade_plan_id": TRADE_PLAN_ID,
        "as_of": AS_OF,
        "expires_at": EXPIRES_AT,
        "research_identity": "synthetic-specialist-contract-fixtures-v1",
        "policy_fingerprint": POLICY_FINGERPRINT,
    }
    arguments.update(overrides)
    return arguments


def evaluated_opinion(**overrides: object):
    arguments = base_arguments(
        evaluation_status=EVALUATED,
        opinion_code="STRUCTURE_SUPPORTS",
        directional_bias=BULLISH,
        evidence_refs=(evidence_ref(),),
        feature_families=("CANDLE_STRUCTURE",),
        confidence=unavailable_confidence(),
        reason_codes=("BREAKOUT_LEVEL_HELD",),
        explanation="Synthetic contract fixture; not a trade recommendation.",
    )
    arguments.update(overrides)
    return build_specialist_opinion(**arguments)


if __name__ == "__main__":
    unittest.main()
