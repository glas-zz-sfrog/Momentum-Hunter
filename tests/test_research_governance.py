from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import momentum_hunter.research_governance as rg


UTC = timezone.utc
CREATED = datetime(2026, 8, 14, 18, 0, tzinfo=UTC)


def _sha(character: str) -> str:
    return character * 64


def _git(character: str) -> str:
    return character * 40


def _resign(value, fingerprint_field: str, namespace: str, **changes):
    changed = dataclasses.replace(value, **changes)
    payload = {
        field.name: getattr(changed, field.name)
        for field in dataclasses.fields(changed)
        if field.name != fingerprint_field
    }
    return dataclasses.replace(
        changed, **{fingerprint_field: rg._fingerprint(namespace, payload)}
    )


def _experiment(
    *,
    experiment_id: str = "experiment-one",
    research_timing: str = rg.PROSPECTIVE,
    research_intent: str = rg.CONFIRMATORY,
    holdout: bool = True,
    planned_minimum_sample: int = 10,
    planned_variants: int = 1,
):
    sample = rg.build_sample_identity(
        sample_identity=f"{experiment_id}-sample",
        policy_fingerprint=_sha("a"),
        sample_status="INACTIVE_TEST_ONLY",
    )
    dataset = rg.build_dataset_identity(
        dataset_identity=f"{experiment_id}-dataset",
        dataset_fingerprint=_sha("b"),
        source_fingerprints=(_sha("c"),),
        data_basis_status=rg.UNRESOLVED,
        survivorship_status=rg.UNCONTROLLED,
        security_identity_status=rg.INSUFFICIENT,
        point_in_time_universe_status=rg.INSUFFICIENT,
    )
    feature = rg.build_feature_definition(
        feature_id="distance-from-vwap",
        feature_version="provider-authoritative-v1",
        semantic_description="Distance from provider-authoritative VWAP.",
        inputs=("provider-vwap", "last-price"),
        transformation="(last-price - provider-vwap) / provider-vwap",
        time_horizon="same session",
        price_basis_requirement="PROVIDER_AUTHORITATIVE_VWAP",
        evidence_family="TECHNICAL_STRUCTURE",
    )
    metric = rg.build_metric_definition(
        metric_id="expected-r",
        metric_version="1",
        semantic_description="Mean stored executable R outcome.",
        formula="sum(executable_r) / count(valid_outcomes)",
        direction="HIGHER_IS_BETTER",
        role=rg.PREREGISTERED_PRIMARY,
    )
    benchmark = rg.build_benchmark_definition(
        benchmark_id="current-momentum-baseline",
        benchmark_version="1",
        semantic_description="Frozen current Momentum baseline.",
        source_identity="momentum-baseline-v1",
    )
    success = rg.build_criterion_definition(
        criterion_id="expected-r-improves",
        criterion_kind="SUCCESS",
        metric_id=metric.metric_id,
        comparator="GT",
        threshold=0.0,
        semantic_description="Expected R improves over baseline.",
    )
    failure = rg.build_criterion_definition(
        criterion_id="expected-r-does-not-improve",
        criterion_kind="FAILURE",
        metric_id=metric.metric_id,
        comparator="LTE",
        threshold=0.0,
        semantic_description="Expected R does not improve over baseline.",
    )
    periods = [
        (rg.TRAIN, datetime(2026, 8, 15, tzinfo=UTC), datetime(2026, 8, 20, tzinfo=UTC)),
        (rg.VALIDATION, datetime(2026, 8, 20, tzinfo=UTC), datetime(2026, 8, 25, tzinfo=UTC)),
        (rg.TEST, datetime(2026, 8, 25, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)),
    ]
    if holdout:
        periods.append(
            (rg.HOLDOUT, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 8, tzinfo=UTC))
        )
    partitions = tuple(
        rg.build_data_partition(
            role=role,
            starts_at=start,
            ends_at=end,
            sample=sample,
            dataset=dataset,
        )
        for role, start, end in periods
    )
    holdout_policy = (
        rg.build_holdout_policy(
            initial_state=rg.SEALED,
            holdout_identity=_sha("d"),
            final_access_not_before=datetime(2026, 9, 1, tzinfo=UTC),
            final_access_gate="Final evaluation only after test partition is frozen.",
        )
        if holdout
        else rg.build_holdout_policy(initial_state=rg.NOT_APPLICABLE)
    )
    allowed_values = ("20",) if planned_variants == 1 else ("20", "30")
    search = rg.build_parameter_search_policy(
        search_method=(
            rg.SINGLE_PREREGISTERED_VARIANT
            if planned_variants == 1
            else rg.SMALL_BOUNDED_COMPARISON
        ),
        planned_variant_count=planned_variants,
        parameter_space=(
            rg.build_parameter_space(parameter_name="window", allowed_values=allowed_values),
        ),
        allowed_feature_set_fingerprints=(rg._feature_set_fingerprint((feature,)),),
        allowed_model_families=("RULE_MODEL",),
        planned_metric_count=1,
        planned_feature_set_count=1,
    )
    experiment = rg.build_research_experiment(
        experiment_id=experiment_id,
        experiment_version="1",
        title="Prospective research contract",
        research_question="Does the feature add information beyond baseline?",
        hypothesis="The preregistered feature improves expected R.",
        created_at=CREATED,
        preregistered_at=CREATED,
        research_domain="TECHNICAL_STRUCTURE",
        research_timing=research_timing,
        research_intent=research_intent,
        code_git_identity=_git("e"),
        policy_fingerprint=_sha("f"),
        input_sample_identities=(sample,),
        input_dataset_identities=(dataset,),
        feature_definitions=(feature,),
        metric_definitions=(metric,),
        benchmark_definition=benchmark,
        success_criteria=(success,),
        failure_criteria=(failure,),
        data_partitions=partitions,
        holdout_policy=holdout_policy,
        parameter_search_policy=search,
        planned_minimum_sample=planned_minimum_sample,
    )
    return experiment, dataset, metric


def _variant(
    experiment,
    dataset,
    *,
    variant_id="variant-one",
    window="20",
    status=rg.EVALUATED,
    result_id="result-one",
    created_at="2026-08-20T14:00:00Z",
):
    evaluated_at = "2026-09-08T21:00:00Z" if status in {rg.EVALUATED, rg.NULL_RESULT} else None
    return rg.build_experiment_variant(
        experiment=experiment,
        variant_id=variant_id,
        parameter_values={"window": window},
        feature_set_identity="default-feature-set",
        feature_set_fingerprint=rg._feature_set_fingerprint(experiment.feature_definitions),
        model_identity="RULE_MODEL",
        created_at=created_at,
        evaluated_at=evaluated_at,
        data_identity=dataset.dataset_identity,
        data_fingerprint=dataset.fingerprint,
        code_identity=experiment.code_git_identity,
        result_identity=result_id if status in {rg.EVALUATED, rg.NULL_RESULT} else None,
        status=status,
        status_reason=(
            "Preserved negative variant state."
            if status in {rg.FAILED, rg.INVALID, rg.ABANDONED_WITH_REASON}
            else None
        ),
    )


def _receipt(experiment, *, early=False):
    return rg.build_holdout_access_receipt(
        experiment=experiment,
        receipt_id="holdout-access-one",
        accessed_at=("2026-08-30T12:00:00Z" if early else "2026-09-01T12:00:00Z"),
        reason="Final preregistered evaluation." if not early else "Premature inspection.",
        authorization_state=(rg.EARLY_ACCESS if early else rg.FINAL_EVALUATION_AUTHORIZED),
    )


def _result(
    experiment,
    variant,
    metric,
    *,
    receipts=(),
    conclusion=rg.SUPPORTED,
    actual_sample=10,
    actual_variant_count=1,
    actual_feature_set_count=1,
):
    observation = rg.build_metric_observation(definition=metric, value=0.25)
    holdout_state = rg._derive_holdout_state(experiment, receipts)
    return rg.build_experiment_result(
        experiment=experiment,
        variant=variant,
        evaluated_at="2026-09-08T21:01:00Z",
        input_data_fingerprint=_sha("9"),
        partition_fingerprints=tuple(item.fingerprint for item in experiment.data_partitions),
        metrics=(observation,),
        benchmark_metrics=(rg.build_metric_observation(definition=metric, value=0.0),),
        conclusion=conclusion,
        limitations=("Synthetic contract evidence only.",),
        holdout_state=holdout_state,
        holdout_access_receipts=receipts,
        actual_sample=actual_sample,
        actual_variant_count=actual_variant_count,
        actual_metric_count=1,
        actual_feature_set_count=actual_feature_set_count,
        selection_occurred=False,
    )


class ResearchGovernanceContractTests(unittest.TestCase):
    def test_contracts_are_frozen_and_research_only(self):
        experiment, _, _ = _experiment()
        self.assertEqual(rg.RESEARCH_ONLY, experiment.authority)
        self.assertEqual(rg.EXECUTION_AUTHORITY_NONE, experiment.execution_authority)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            experiment.title = "Changed"

    def test_historically_robust_claim_requires_all_verified_states(self):
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Historically robust"):
            rg.build_dataset_identity(
                dataset_identity="weak-data",
                dataset_fingerprint=_sha("a"),
                source_fingerprints=(_sha("b"),),
                data_basis_status=rg.UNRESOLVED,
                survivorship_status=rg.UNCONTROLLED,
                security_identity_status=rg.INSUFFICIENT,
                point_in_time_universe_status=rg.INSUFFICIENT,
                historically_robust=True,
            )

    def test_experiment_tamper_and_execution_authority_fail(self):
        experiment, _, _ = _experiment()
        altered = dataclasses.replace(experiment, title="Hindsight title")
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "fingerprint"):
            rg.validate_research_experiment(altered)
        resigned = _resign(
            experiment,
            "fingerprint",
            "research-experiment-v1",
            authority="TRADING_AUTHORITY",
            execution_authority="ORDER_TRANSMISSION",
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "authority"):
            rg.validate_research_experiment(resigned)

    def test_unregistered_feature_and_criterion_drift_fail(self):
        experiment, _, _ = _experiment()
        changed_feature = rg.build_feature_definition(
            feature_id="new-feature",
            feature_version="1",
            semantic_description="Not preregistered.",
            inputs=("x",),
            transformation="x",
            time_horizon="daily",
            price_basis_requirement="UNRESOLVED",
            evidence_family="OTHER",
        )
        altered = _resign(
            experiment,
            "fingerprint",
            "research-experiment-v1",
            feature_definitions=(changed_feature,),
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "feature set"):
            rg.validate_research_experiment(altered)
        criterion = _resign(
            experiment.success_criteria[0],
            "fingerprint",
            "criterion-definition-v1",
            threshold=99.0,
        )
        altered = _resign(
            experiment,
            "fingerprint",
            "research-experiment-v1",
            success_criteria=(criterion,),
        )
        rg.validate_research_experiment(altered)
        self.assertNotEqual(experiment.fingerprint, altered.fingerprint)

    def test_independent_partitions_cannot_overlap(self):
        experiment, _, _ = _experiment()
        overlapping = _resign(
            experiment.data_partitions[1],
            "fingerprint",
            "data-partition-v1",
            starts_at="2026-08-19T00:00:00.000000Z",
        )
        altered = _resign(
            experiment,
            "fingerprint",
            "research-experiment-v1",
            data_partitions=(experiment.data_partitions[0], overlapping) + experiment.data_partitions[2:],
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "overlap"):
            rg.validate_research_experiment(altered)

    def test_post_outcome_amendment_cannot_be_labeled_pre_outcome(self):
        experiment, _, _ = _experiment()
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "post-outcome"):
            rg.build_experiment_amendment(
                experiment=experiment,
                amendment_id="amendment-one",
                amendment_time="2026-09-09T00:00:00Z",
                reason="Outcome already known.",
                changed_fields=("hypothesis",),
                new_fingerprint=_sha("1"),
                outcome_knowledge_status=rg.PRE_OUTCOME_AMENDMENT,
                first_outcome_time="2026-09-08T21:00:00Z",
            )

    def test_lifecycle_chronology_cannot_precede_preregistration(self):
        experiment, dataset, metric = _experiment()
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Variant cannot precede"):
            _variant(
                experiment,
                dataset,
                status=rg.FAILED,
                created_at="2026-08-13T00:00:00Z",
            )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Amendment cannot precede"):
            rg.build_experiment_amendment(
                experiment=experiment,
                amendment_id="too-early-amendment",
                amendment_time="2026-08-13T00:00:00Z",
                reason="Impossible chronology.",
                changed_fields=("hypothesis",),
                new_fingerprint=_sha("1"),
                outcome_knowledge_status=rg.PRE_OUTCOME_AMENDMENT,
            )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Holdout access cannot precede"):
            rg.build_holdout_access_receipt(
                experiment=experiment,
                receipt_id="too-early-access",
                accessed_at="2026-08-13T00:00:00Z",
                reason="Impossible chronology.",
                authorization_state=rg.EARLY_ACCESS,
            )
        variant = _variant(experiment, dataset)
        observation = rg.build_metric_observation(definition=metric, value=0.1)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Result cannot precede"):
            rg.build_experiment_result(
                experiment=experiment,
                variant=variant,
                evaluated_at="2026-08-13T00:00:00Z",
                input_data_fingerprint=_sha("2"),
                partition_fingerprints=tuple(item.fingerprint for item in experiment.data_partitions),
                metrics=(observation,),
                benchmark_metrics=(),
                conclusion=rg.SUPPORTED,
                limitations=(),
                holdout_state=rg.SEALED,
                holdout_access_receipts=(),
                actual_sample=10,
                actual_variant_count=1,
                actual_metric_count=1,
                actual_feature_set_count=1,
                selection_occurred=False,
            )

    def test_preregistered_benchmark_metric_criteria_and_policy_cannot_be_replaced(self):
        experiment, _, _ = _experiment()
        benchmark = rg.build_benchmark_definition(
            benchmark_id=experiment.benchmark_definition.benchmark_id,
            benchmark_version=experiment.benchmark_definition.benchmark_version,
            semantic_description="A favorable benchmark chosen after the outcome.",
            source_identity="hindsight-baseline",
        )
        metric = rg.build_metric_definition(
            metric_id=experiment.metric_definitions[0].metric_id,
            metric_version=experiment.metric_definitions[0].metric_version,
            semantic_description="A changed primary endpoint.",
            formula="max(executable_r)",
            direction="HIGHER_IS_BETTER",
            role=rg.PREREGISTERED_PRIMARY,
        )
        criterion = _resign(
            experiment.success_criteria[0],
            "fingerprint",
            "criterion-definition-v1",
            threshold=-99.0,
        )
        changed_records = (
            _resign(
                experiment,
                "fingerprint",
                "research-experiment-v1",
                benchmark_definition=benchmark,
            ),
            _resign(
                experiment,
                "fingerprint",
                "research-experiment-v1",
                metric_definitions=(metric,),
            ),
            _resign(
                experiment,
                "fingerprint",
                "research-experiment-v1",
                success_criteria=(criterion,),
            ),
            _resign(
                experiment,
                "fingerprint",
                "research-experiment-v1",
                policy_fingerprint=_sha("7"),
            ),
        )
        for changed in changed_records:
            rg.validate_research_experiment(changed)
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Duplicate Experiment identity"):
                rg.audit_registry_snapshot(
                    rg.RegistrySnapshot(experiments=(experiment, changed))
                )

    def test_variant_outside_search_space_is_explicit_invalid(self):
        experiment, dataset, _ = _experiment()
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "must be recorded as invalid"):
            _variant(experiment, dataset, window="999")
        invalid = _variant(
            experiment,
            dataset,
            variant_id="invalid-variant",
            window="999",
            status=rg.INVALID,
        )
        self.assertEqual(rg.UNPLANNED_SEARCH_EXPANSION, invalid.search_space_status)

    def test_variant_rejects_data_policy_and_code_identity_drift(self):
        experiment, dataset, _ = _experiment()
        kwargs = dict(
            experiment=experiment,
            variant_id="drifted",
            parameter_values={"window": "20"},
            feature_set_identity="default-feature-set",
            feature_set_fingerprint=rg._feature_set_fingerprint(experiment.feature_definitions),
            model_identity="RULE_MODEL",
            created_at="2026-08-20T14:00:00Z",
            evaluated_at="2026-09-08T21:00:00Z",
            data_identity=dataset.dataset_identity,
            result_identity="result-drifted",
            status=rg.EVALUATED,
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "data identity"):
            rg.build_experiment_variant(
                **kwargs, data_fingerprint=_sha("7"), code_identity=experiment.code_git_identity
            )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "code identity"):
            rg.build_experiment_variant(
                **kwargs, data_fingerprint=dataset.fingerprint, code_identity=_git("7")
            )

    def test_result_requires_registered_primary_metric_and_minimum_sample(self):
        experiment, dataset, metric = _experiment(planned_minimum_sample=10)
        variant = _variant(experiment, dataset)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "minimum"):
            _result(experiment, variant, metric, actual_sample=2)
        insufficient = _result(
            experiment,
            variant,
            metric,
            conclusion=rg.INSUFFICIENT_SAMPLE,
            actual_sample=2,
        )
        self.assertEqual(rg.INSUFFICIENT_SAMPLE, insufficient.conclusion)
        other_metric = rg.build_metric_definition(
            metric_id="surprise-metric",
            metric_version="1",
            semantic_description="Not the preregistered endpoint.",
            formula="x",
            direction="HIGHER_IS_BETTER",
            role=rg.PREREGISTERED_PRIMARY,
        )
        observation = rg.build_metric_observation(definition=other_metric, value=1.0)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "preregistered"):
            rg.build_experiment_result(
                experiment=experiment,
                variant=variant,
                evaluated_at="2026-09-08T21:01:00Z",
                input_data_fingerprint=_sha("9"),
                partition_fingerprints=tuple(item.fingerprint for item in experiment.data_partitions),
                metrics=(observation,),
                benchmark_metrics=(),
                conclusion=rg.SUPPORTED,
                limitations=(),
                holdout_state=rg.SEALED,
                holdout_access_receipts=(),
                actual_sample=10,
                actual_variant_count=1,
                actual_metric_count=1,
                actual_feature_set_count=1,
                selection_occurred=False,
            )

    def test_exploratory_result_cannot_be_relabelled_confirmatory(self):
        experiment, dataset, metric = _experiment(research_intent=rg.EXPLORATORY)
        variant = _variant(experiment, dataset)
        result = _result(experiment, variant, metric)
        self.assertEqual(rg.EXPLORATORY, result.research_intent)
        relabelled = _resign(
            result,
            "result_fingerprint",
            "experiment-result-v1",
            research_intent=rg.CONFIRMATORY,
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "identity drift"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(variant,), results=(relabelled,)
                )
            )

    def test_legitimate_holdout_open_and_early_contamination_are_permanent(self):
        experiment, dataset, metric = _experiment()
        variant = _variant(experiment, dataset)
        final_receipt = _receipt(experiment)
        result = _result(experiment, variant, metric, receipts=(final_receipt,))
        self.assertEqual(rg.OPENED_FOR_FINAL_EVALUATION, result.holdout_state)
        early = _receipt(experiment, early=True)
        self.assertEqual(rg.CONTAMINATED_BY_EARLY_ACCESS, early.resulting_holdout_state)
        contaminated = _result(
            experiment,
            variant,
            metric,
            receipts=(early,),
            conclusion=rg.HOLDOUT_CONTAMINATED,
        )
        self.assertEqual(rg.HOLDOUT_CONTAMINATED, contaminated.conclusion)

    def test_holdout_cannot_be_resealed_or_falsely_claimed_sealed(self):
        experiment, dataset, metric = _experiment()
        variant = _variant(experiment, dataset)
        early = _receipt(experiment, early=True)
        false_reseal = _resign(
            early,
            "fingerprint",
            "holdout-access-receipt-v1",
            receipt_id="second-receipt",
            accessed_at="2026-09-02T00:00:00.000000Z",
            prior_access_count=1,
            prior_receipt_fingerprint=early.fingerprint,
            resulting_holdout_state=rg.OPENED_FOR_FINAL_EVALUATION,
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "cannot be resealed"):
            rg._derive_holdout_state(experiment, (early, false_reseal))
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "contradicts"):
            rg.build_experiment_result(
                experiment=experiment,
                variant=variant,
                evaluated_at="2026-09-08T21:01:00Z",
                input_data_fingerprint=_sha("9"),
                partition_fingerprints=tuple(item.fingerprint for item in experiment.data_partitions),
                metrics=(rg.build_metric_observation(definition=metric, value=0.1),),
                benchmark_metrics=(),
                conclusion=rg.SUPPORTED,
                limitations=(),
                holdout_state=rg.SEALED,
                holdout_access_receipts=(early,),
                actual_sample=10,
                actual_variant_count=1,
                actual_metric_count=1,
                actual_feature_set_count=1,
                selection_occurred=False,
            )

    def test_snapshot_rejects_missing_result_variant_and_holdout_receipt(self):
        experiment, dataset, metric = _experiment()
        variant = _variant(experiment, dataset)
        receipt = _receipt(experiment)
        result = _result(experiment, variant, metric, receipts=(receipt,))
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "result is missing"):
            rg.audit_registry_snapshot(rg.RegistrySnapshot(experiments=(experiment,), variants=(variant,)))
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "receipt was deleted"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(variant,), results=(result,)
                )
            )

    def test_snapshot_rejects_wrong_experiment_variant_and_timing(self):
        experiment, dataset, metric = _experiment()
        other, _, _ = _experiment(experiment_id="experiment-two")
        variant = _variant(experiment, dataset)
        result = _result(experiment, variant, metric)
        wrong_experiment = _resign(
            result,
            "result_fingerprint",
            "experiment-result-v1",
            experiment_id=other.experiment_id,
            experiment_fingerprint=other.fingerprint,
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "experiment.*wrong|wrong experiment"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment, other),
                    variants=(variant,),
                    results=(wrong_experiment,),
                )
            )
        wrong_timing = _resign(
            result,
            "result_fingerprint",
            "experiment-result-v1",
            research_timing=rg.RETROSPECTIVE_CONFIRMATORY,
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "identity drift"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(variant,), results=(wrong_timing,)
                )
            )

    def test_result_before_experiment_registration_and_wrong_variant_fail(self):
        experiment, dataset, metric = _experiment()
        variant = _variant(experiment, dataset)
        result = _result(experiment, variant, metric)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "wrong experiment"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(variants=(variant,), results=(result,))
            )
        wrong_variant = _resign(
            result,
            "result_fingerprint",
            "experiment-result-v1",
            variant_id="missing-variant",
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "wrong variant"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(variant,), results=(wrong_variant,)
                )
            )

    def test_duplicate_variant_identity_and_silent_variant_deletion_fail(self):
        experiment, dataset, metric = _experiment(planned_variants=2)
        first = _variant(experiment, dataset)
        duplicate = _variant(experiment, dataset)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Duplicate Variant identity"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(experiments=(experiment,), variants=(first, duplicate))
            )
        failed = _variant(
            experiment,
            dataset,
            variant_id="failed-variant",
            window="30",
            status=rg.FAILED,
            created_at="2026-08-20T13:00:00Z",
        )
        result = _result(
            experiment,
            first,
            metric,
            conclusion=rg.NOT_SUPPORTED,
            actual_variant_count=2,
        )
        rg.audit_registry_snapshot(
            rg.RegistrySnapshot(
                experiments=(experiment,), variants=(failed, first), results=(result,)
            )
        )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "attempted-variant count"):
            rg.audit_registry_snapshot(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(first,), results=(result,)
                )
            )

    def test_summary_preserves_failed_variants_and_negative_results(self):
        experiment, dataset, metric = _experiment(planned_variants=2)
        failed = _variant(
            experiment,
            dataset,
            variant_id="failed-variant",
            window="30",
            status=rg.FAILED,
            created_at="2026-08-20T13:00:00Z",
        )
        variant = _variant(experiment, dataset)
        result = _result(
            experiment,
            variant,
            metric,
            conclusion=rg.NOT_SUPPORTED,
            actual_variant_count=2,
        )
        snapshot = rg.RegistrySnapshot(
            experiments=(experiment,), variants=(failed, variant), results=(result,)
        )
        summary = rg.summarize_registry(snapshot)
        self.assertEqual(2, summary.variants_attempted)
        self.assertEqual(1, dict(summary.variant_status_counts)[rg.FAILED])
        self.assertEqual(1, dict(summary.result_conclusion_counts)[rg.NOT_SUPPORTED])
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "attempted-variant count"):
            rg.summarize_registry(
                rg.RegistrySnapshot(
                    experiments=(experiment,), variants=(variant,), results=(result,)
                )
            )

    def test_invalidation_is_additive_not_destructive(self):
        experiment, _, _ = _experiment()
        invalidation = rg.build_experiment_invalidation(
            experiment=experiment,
            invalidation_id="invalid-one",
            invalidation_reason="Incomplete denominator discovered.",
            invalidated_at="2026-09-09T00:00:00Z",
            evidence_fingerprint=_sha("8"),
        )
        snapshot = rg.RegistrySnapshot(
            experiments=(experiment,), invalidations=(invalidation,)
        )
        rg.audit_registry_snapshot(snapshot)
        self.assertEqual(1, len(snapshot.experiments))
        self.assertEqual(1, len(snapshot.invalidations))


class ModelHealthTests(unittest.TestCase):
    def _policy(self):
        benchmark = rg.build_benchmark_definition(
            benchmark_id="health-benchmark",
            benchmark_version="1",
            semantic_description="Frozen health benchmark.",
            source_identity="research-only-baseline",
        )
        metric = rg.build_model_health_metric_definition(
            metric_id="calibration-error",
            metric_version="1",
            semantic_description="Absolute calibration error.",
            formula="abs(predicted - observed)",
            failure_comparator="GT",
            failure_threshold=0.2,
        )
        policy = rg.build_model_health_policy(
            policy_id="health-policy",
            policy_version="1",
            evidence_window="rolling 30 prospective opportunities",
            minimum_sample=30,
            benchmark=benchmark,
            health_metrics=(metric,),
            failure_threshold_policy="UNRELIABLE when preregistered metric exceeds threshold.",
        )
        return policy, metric

    def test_policy_fingerprint_changes_with_threshold(self):
        policy, metric = self._policy()
        changed_metric = rg.build_model_health_metric_definition(
            metric_id=metric.metric_id,
            metric_version=metric.metric_version,
            semantic_description=metric.semantic_description,
            formula=metric.formula,
            failure_comparator=metric.failure_comparator,
            failure_threshold=0.3,
        )
        benchmark = rg.build_benchmark_definition(
            benchmark_id="health-benchmark",
            benchmark_version="1",
            semantic_description="Frozen health benchmark.",
            source_identity="research-only-baseline",
        )
        changed = rg.build_model_health_policy(
            policy_id="health-policy",
            policy_version="1",
            evidence_window=policy.evidence_window,
            minimum_sample=policy.minimum_sample,
            benchmark=benchmark,
            health_metrics=(changed_metric,),
            failure_threshold_policy=policy.failure_threshold_policy,
        )
        self.assertNotEqual(policy.fingerprint, changed.fingerprint)

    def test_synthetic_or_small_sample_cannot_claim_healthy(self):
        policy, metric = self._policy()
        observation = rg.build_model_health_metric_observation(definition=metric, value=0.1)
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "cannot prove health"):
            rg.build_model_health_record(
                policy=policy,
                record_id="health-one",
                model_identity="REGIME_EXHAUSTION",
                model_version="1",
                evaluated_at="2026-09-30T00:00:00Z",
                sample_size=100,
                health_metrics=(observation,),
                health_state=rg.HEALTHY,
                reason_codes=(),
                evidence_kind=rg.UNIT_TEST_ONLY,
                evidence_fingerprint=_sha("1"),
            )
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "Insufficient sample"):
            rg.build_model_health_record(
                policy=policy,
                record_id="health-two",
                model_identity="REGIME_EXHAUSTION",
                model_version="1",
                evaluated_at="2026-09-30T00:00:00Z",
                sample_size=2,
                health_metrics=(observation,),
                health_state=rg.HEALTHY,
                reason_codes=(),
                evidence_kind=rg.PROSPECTIVE_OUTCOME_EVIDENCE,
                evidence_fingerprint=_sha("2"),
            )

    def test_not_evaluated_health_has_no_authority(self):
        policy, metric = self._policy()
        observation = rg.build_model_health_metric_observation(
            definition=metric, value=None, status="NOT_EVALUATED"
        )
        record = rg.build_model_health_record(
            policy=policy,
            record_id="health-none",
            model_identity="EVENT_SHOCK",
            model_version="1",
            evaluated_at="2026-09-30T00:00:00Z",
            sample_size=0,
            health_metrics=(observation,),
            health_state=rg.NOT_EVALUATED,
            reason_codes=("NO_PROSPECTIVE_OUTCOMES",),
            evidence_kind=rg.SYNTHETIC_EVIDENCE,
            evidence_fingerprint=_sha("3"),
        )
        self.assertEqual(rg.EXECUTION_AUTHORITY_NONE, record.execution_authority)
        summary = rg.summarize_registry(
            rg.RegistrySnapshot(
                model_health_policies=(policy,), model_health_records=(record,)
            )
        )
        self.assertEqual(1, dict(summary.model_health_state_counts)[rg.NOT_EVALUATED])


class RegistryPersistenceTests(unittest.TestCase):
    def _complete_records(self):
        experiment, dataset, metric = _experiment(holdout=False)
        variant = _variant(experiment, dataset)
        result = _result(experiment, variant, metric)
        return experiment, variant, result

    def test_write_once_duplicate_restart_and_summary(self):
        experiment, variant, result = self._complete_records()
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            paths = [store.write(item) for item in (experiment, variant, result)]
            self.assertEqual(paths[0], store.write(experiment))
            restarted = rg.ResearchRegistryStore(Path(temporary).resolve())
            snapshot = restarted.load_snapshot()
            self.assertEqual(1, rg.summarize_registry(snapshot).experiments_registered)

    def test_conflicting_duplicate_fails_closed(self):
        experiment, _, _ = self._complete_records()
        changed = rg.build_research_experiment(
            experiment_id=experiment.experiment_id,
            experiment_version=experiment.experiment_version,
            title="Conflicting same identity",
            research_question=experiment.research_question,
            hypothesis=experiment.hypothesis,
            created_at=rg._parse_timestamp(experiment.created_at),
            preregistered_at=rg._parse_timestamp(experiment.preregistered_at),
            research_domain=experiment.research_domain,
            research_timing=experiment.research_timing,
            research_intent=experiment.research_intent,
            code_git_identity=experiment.code_git_identity,
            policy_fingerprint=experiment.policy_fingerprint,
            input_sample_identities=experiment.input_sample_identities,
            input_dataset_identities=experiment.input_dataset_identities,
            feature_definitions=experiment.feature_definitions,
            metric_definitions=experiment.metric_definitions,
            benchmark_definition=experiment.benchmark_definition,
            success_criteria=experiment.success_criteria,
            failure_criteria=experiment.failure_criteria,
            data_partitions=experiment.data_partitions,
            holdout_policy=experiment.holdout_policy,
            parameter_search_policy=experiment.parameter_search_policy,
            planned_minimum_sample=experiment.planned_minimum_sample,
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            store.write(experiment)
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Conflicting write-once"):
                store.write(changed)

    def test_tampered_malformed_and_duplicate_key_records_fail(self):
        experiment, _, _ = self._complete_records()
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            path = store.write(experiment)
            text = path.read_text(encoding="utf-8").replace(
                "Prospective research contract", "Retrospective research contract"
            )
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Invalid registry record"):
                store.load_snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            directory = store.root / "experiments"
            directory.mkdir(parents=True)
            (directory / "bad.json").write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Malformed"):
                store.load_snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            directory = store.root / "experiments"
            directory.mkdir(parents=True)
            (directory / "bad.json").write_text(
                '{"recordType":"ResearchExperiment","recordType":"ResearchExperiment","record":{}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Duplicate JSON key"):
                store.load_snapshot()

    def test_partial_write_is_not_accepted_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = rg.ResearchRegistryStore(Path(temporary).resolve())
            directory = store.root / "experiments"
            directory.mkdir(parents=True)
            (directory / ".experiment.json.deadbeef.tmp").write_bytes(b'{"partial":')
            with self.assertRaisesRegex(rg.ResearchGovernanceError, "Partial registry write"):
                rg.ResearchRegistryStore(Path(temporary).resolve()).load_snapshot()

    def test_relative_root_is_rejected(self):
        with self.assertRaisesRegex(rg.ResearchGovernanceError, "absolute"):
            rg.ResearchRegistryStore("relative-root")


class StaticCompatibilityTests(unittest.TestCase):
    def test_specialist_fixtures_match_exact_current_identities(self):
        fixtures = {item.specialist_id: item for item in rg.specialist_registration_fixtures()}
        self.assertEqual(
            "99a25f84219377e9988e8284aa15a944e3936784",
            fixtures["REGIME_EXHAUSTION"].source_commit,
        )
        self.assertEqual(
            "codex/ARGUS-REGIME-002-exhaustion-market-stress",
            fixtures["REGIME_EXHAUSTION"].source_branch,
        )
        self.assertEqual(
            "1b105e71d99d45a8ed8099ae4001bd9c6ba2242f",
            fixtures["EXECUTION_QUALITY"].source_commit,
        )
        self.assertEqual(
            "codex/ARGUS-EXEC-QUALITY-001-liquidity-execution-research",
            fixtures["EXECUTION_QUALITY"].source_branch,
        )
        self.assertEqual(
            "fe8ca09556fe8ea3dd81949e59ac26d8e3d86da4",
            fixtures["EVENT_SHOCK"].source_commit,
        )
        self.assertEqual(
            "codex/ARGUS-EVENT-SHOCK-001-event-reaction-research",
            fixtures["EVENT_SHOCK"].source_branch,
        )
        experiments = rg.build_static_specialist_experiments()
        self.assertEqual(3, len(experiments))
        self.assertTrue(all(item.status == rg.PREREGISTERED for item in experiments))
        self.assertTrue(all(not item.input_dataset_identities[0].historically_robust for item in experiments))

    def test_stat_data_is_static_inactive_zero_observation_compatibility(self):
        compatibility = rg.stat_data_compatibility()
        self.assertTrue(compatibility.compatible)
        self.assertEqual("opportunity-denominator-research-v1", compatibility.sample_identity)
        self.assertEqual(0, compatibility.sessions)
        self.assertEqual(0, compatibility.opportunities)
        self.assertEqual("STATIC_IDENTITY_ONLY_NO_RUNTIME_IMPORT", compatibility.import_mode)

    def test_research_data_limitations_are_static_and_not_historically_robust(self):
        compatibility = rg.research_data_compatibility()
        self.assertEqual(rg.UNRESOLVED, compatibility.data_basis_status)
        self.assertEqual(rg.UNCONTROLLED, compatibility.survivorship_status)
        self.assertEqual(rg.UNRESOLVED, compatibility.security_identity_status)
        self.assertEqual(rg.INSUFFICIENT, compatibility.point_in_time_universe_status)
        self.assertFalse(compatibility.historically_robust)

    def test_module_has_no_network_broker_or_runtime_imports(self):
        source = Path(rg.__file__).read_text(encoding="utf-8")
        forbidden = (
            "import requests",
            "import urllib",
            "import socket",
            "alpaca",
            "schwab",
            "FakeBroker",
            "submit_order",
            "RiskGovernor",
            "successor_setup_observer",
            "opportunity_denominator",
        )
        for term in forbidden:
            self.assertNotIn(term, source)

    def test_summary_contains_no_best_model_or_profitability_selector(self):
        fields = {field.name for field in dataclasses.fields(rg.RegistrySummary)}
        self.assertNotIn("best_model", fields)
        self.assertNotIn("profitability_rank", fields)
        self.assertNotIn("promoted_strategy", fields)


if __name__ == "__main__":
    unittest.main()
