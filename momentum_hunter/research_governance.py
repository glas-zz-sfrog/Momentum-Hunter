"""Immutable research experiment registry and model-health contracts.

This module is deliberately downstream of research evidence. It does not
evaluate a strategy, fetch data, inspect an account, contact a broker, select a
model, or participate in Momentum Hunter runtime behavior.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import types
import uuid
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, get_args, get_origin, get_type_hints


CONTRACT_VERSION = 1
REGISTRY_PROFILE = "research-experiment-registry-v1"
REGISTRY_DIRECTORY = "experiment-registry-v1"
RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"
PREREGISTERED = "PREREGISTERED"

PROSPECTIVE = "PROSPECTIVE"
RETROSPECTIVE_EXPLORATORY = "RETROSPECTIVE_EXPLORATORY"
RETROSPECTIVE_CONFIRMATORY = "RETROSPECTIVE_CONFIRMATORY"
RESEARCH_TIMINGS = frozenset(
    {PROSPECTIVE, RETROSPECTIVE_EXPLORATORY, RETROSPECTIVE_CONFIRMATORY}
)
EXPLORATORY = "EXPLORATORY"
CONFIRMATORY = "CONFIRMATORY"
RESEARCH_INTENTS = frozenset({EXPLORATORY, CONFIRMATORY})

TRAIN = "TRAIN"
VALIDATION = "VALIDATION"
TEST = "TEST"
HOLDOUT = "HOLDOUT"
PARTITION_ROLES = frozenset({TRAIN, VALIDATION, TEST, HOLDOUT})

SEALED = "SEALED"
OPENED_FOR_FINAL_EVALUATION = "OPENED_FOR_FINAL_EVALUATION"
CONTAMINATED_BY_EARLY_ACCESS = "CONTAMINATED_BY_EARLY_ACCESS"
NOT_APPLICABLE = "NOT_APPLICABLE"
HOLDOUT_STATES = frozenset(
    {
        SEALED,
        OPENED_FOR_FINAL_EVALUATION,
        CONTAMINATED_BY_EARLY_ACCESS,
        NOT_APPLICABLE,
    }
)
FINAL_EVALUATION_AUTHORIZED = "FINAL_EVALUATION_AUTHORIZED"
EARLY_ACCESS = "EARLY_ACCESS"
UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
HOLDOUT_AUTHORIZATION_STATES = frozenset(
    {FINAL_EVALUATION_AUTHORIZED, EARLY_ACCESS, UNAUTHORIZED_ACCESS}
)

PRE_OUTCOME_AMENDMENT = "PRE_OUTCOME_AMENDMENT"
POST_OUTCOME_AMENDMENT = "POST_OUTCOME_AMENDMENT"
OUTCOME_KNOWLEDGE_STATES = frozenset(
    {PRE_OUTCOME_AMENDMENT, POST_OUTCOME_AMENDMENT}
)

SINGLE_PREREGISTERED_VARIANT = "SINGLE_PREREGISTERED_VARIANT"
SMALL_BOUNDED_COMPARISON = "SMALL_BOUNDED_COMPARISON"
GRID_SEARCH = "GRID_SEARCH"
RANDOM_SEARCH = "RANDOM_SEARCH"
MODEL_SELECTION = "MODEL_SELECTION"
OTHER_VERSIONED_METHOD = "OTHER_VERSIONED_METHOD"
SEARCH_METHODS = frozenset(
    {
        SINGLE_PREREGISTERED_VARIANT,
        SMALL_BOUNDED_COMPARISON,
        GRID_SEARCH,
        RANDOM_SEARCH,
        MODEL_SELECTION,
        EXPLORATORY,
        OTHER_VERSIONED_METHOD,
    }
)

EVALUATED = "EVALUATED"
NULL_RESULT = "NULL_RESULT"
FAILED = "FAILED"
INVALID = "INVALID"
ABANDONED_WITH_REASON = "ABANDONED_WITH_REASON"
VARIANT_STATUSES = frozenset(
    {EVALUATED, NULL_RESULT, FAILED, INVALID, ABANDONED_WITH_REASON}
)
WITHIN_PREREGISTERED_SPACE = "WITHIN_PREREGISTERED_SPACE"
UNPLANNED_SEARCH_EXPANSION = "UNPLANNED_SEARCH_EXPANSION"

SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT_SUPPORTED"
INCONCLUSIVE = "INCONCLUSIVE"
INVALID_DATA = "INVALID_DATA"
INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
HOLDOUT_CONTAMINATED = "HOLDOUT_CONTAMINATED"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
RESULT_CONCLUSIONS = frozenset(
    {
        SUPPORTED,
        NOT_SUPPORTED,
        INCONCLUSIVE,
        INVALID_DATA,
        INVALID_EXPERIMENT,
        HOLDOUT_CONTAMINATED,
        INSUFFICIENT_SAMPLE,
        ABANDONED_WITH_REASON,
    }
)

PREREGISTERED_PRIMARY = "PREREGISTERED_PRIMARY"
PREREGISTERED_SECONDARY = "PREREGISTERED_SECONDARY"
EXPLORATORY_SECONDARY_METRIC = "EXPLORATORY_SECONDARY_METRIC"
METRIC_ROLES = frozenset(
    {
        PREREGISTERED_PRIMARY,
        PREREGISTERED_SECONDARY,
        EXPLORATORY_SECONDARY_METRIC,
    }
)

NOT_EVALUATED = "NOT_EVALUATED"
HEALTHY = "HEALTHY"
DEGRADING = "DEGRADING"
UNRELIABLE = "UNRELIABLE"
INSUFFICIENT_RECENT_EVIDENCE = "INSUFFICIENT_RECENT_EVIDENCE"
MODEL_HEALTH_STATES = frozenset(
    {
        NOT_EVALUATED,
        HEALTHY,
        DEGRADING,
        UNRELIABLE,
        INSUFFICIENT_RECENT_EVIDENCE,
    }
)
UNIT_TEST_ONLY = "UNIT_TEST_ONLY"
SYNTHETIC_EVIDENCE = "SYNTHETIC_EVIDENCE"
PROSPECTIVE_OUTCOME_EVIDENCE = "PROSPECTIVE_OUTCOME_EVIDENCE"
HEALTH_EVIDENCE_KINDS = frozenset(
    {UNIT_TEST_ONLY, SYNTHETIC_EVIDENCE, PROSPECTIVE_OUTCOME_EVIDENCE}
)

VERIFIED = "VERIFIED"
UNRESOLVED = "UNRESOLVED"
INSUFFICIENT = "INSUFFICIENT"
CONTROLLED = "CONTROLLED"
UNCONTROLLED = "UNCONTROLLED"
DATA_STATUS_VALUES = frozenset(
    {VERIFIED, UNRESOLVED, INSUFFICIENT, CONTROLLED, UNCONTROLLED, NOT_APPLICABLE}
)

_SHA256 = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
_GIT_SHA = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")


class ResearchGovernanceError(ValueError):
    """Raised when registry evidence is malformed, contradictory, or unsafe."""


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    feature_version: str
    semantic_description: str
    inputs: tuple[str, ...]
    transformation: str
    time_horizon: str
    price_basis_requirement: str
    evidence_family: str
    fingerprint: str


@dataclass(frozen=True)
class SampleIdentity:
    sample_identity: str
    policy_fingerprint: str
    sample_status: str
    fingerprint: str


@dataclass(frozen=True)
class DatasetIdentity:
    dataset_identity: str
    dataset_fingerprint: str
    source_fingerprints: tuple[str, ...]
    data_basis_status: str
    survivorship_status: str
    security_identity_status: str
    point_in_time_universe_status: str
    historically_robust: bool
    fingerprint: str


@dataclass(frozen=True)
class DataPartition:
    role: str
    starts_at: str
    ends_at: str
    sample_identity: str
    sample_fingerprint: str
    dataset_identity: str
    dataset_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    metric_version: str
    semantic_description: str
    formula: str
    direction: str
    role: str
    fingerprint: str


@dataclass(frozen=True)
class BenchmarkDefinition:
    benchmark_id: str
    benchmark_version: str
    semantic_description: str
    source_identity: str
    fingerprint: str


@dataclass(frozen=True)
class CriterionDefinition:
    criterion_id: str
    criterion_kind: str
    metric_id: str
    comparator: str
    threshold: float
    semantic_description: str
    fingerprint: str


@dataclass(frozen=True)
class ParameterSpace:
    parameter_name: str
    allowed_values: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ParameterSearchPolicy:
    search_method: str
    planned_variant_count: int
    parameter_space: tuple[ParameterSpace, ...]
    allowed_feature_set_fingerprints: tuple[str, ...]
    allowed_model_families: tuple[str, ...]
    planned_metric_count: int
    planned_feature_set_count: int
    fingerprint: str


@dataclass(frozen=True)
class HoldoutPolicy:
    initial_state: str
    holdout_identity: str | None
    final_access_not_before: str | None
    final_access_gate: str | None
    fingerprint: str


@dataclass(frozen=True)
class ResearchExperiment:
    contract_version: int
    profile: str
    experiment_id: str
    experiment_version: str
    title: str
    research_question: str
    hypothesis: str
    created_at: str
    preregistered_at: str
    research_domain: str
    research_timing: str
    research_intent: str
    code_git_identity: str
    policy_fingerprint: str
    input_sample_identities: tuple[SampleIdentity, ...]
    input_dataset_identities: tuple[DatasetIdentity, ...]
    feature_definitions: tuple[FeatureDefinition, ...]
    metric_definitions: tuple[MetricDefinition, ...]
    benchmark_definition: BenchmarkDefinition
    success_criteria: tuple[CriterionDefinition, ...]
    failure_criteria: tuple[CriterionDefinition, ...]
    data_partitions: tuple[DataPartition, ...]
    require_independent_partitions: bool
    holdout_policy: HoldoutPolicy
    parameter_search_policy: ParameterSearchPolicy
    planned_minimum_sample: int
    authority: str
    execution_authority: str
    status: str
    fingerprint: str


def build_feature_definition(
    *,
    feature_id: str,
    feature_version: str,
    semantic_description: str,
    inputs: Sequence[str],
    transformation: str,
    time_horizon: str,
    price_basis_requirement: str,
    evidence_family: str,
) -> FeatureDefinition:
    payload = {
        "feature_id": _token(feature_id, "Feature ID"),
        "feature_version": _token(feature_version, "Feature version"),
        "semantic_description": _text(semantic_description, "Feature description"),
        "inputs": _tokens(inputs, "Feature inputs"),
        "transformation": _text(transformation, "Feature transformation"),
        "time_horizon": _text(time_horizon, "Feature time horizon"),
        "price_basis_requirement": _token(
            price_basis_requirement, "Feature price-basis requirement"
        ),
        "evidence_family": _token(evidence_family, "Feature evidence family"),
    }
    value = FeatureDefinition(**payload, fingerprint=_fingerprint("feature-definition-v1", payload))
    validate_feature_definition(value)
    return value


def build_sample_identity(
    *, sample_identity: str, policy_fingerprint: str, sample_status: str
) -> SampleIdentity:
    payload = {
        "sample_identity": _token(sample_identity, "Sample identity"),
        "policy_fingerprint": _sha256(policy_fingerprint, "Sample policy fingerprint"),
        "sample_status": _token(sample_status, "Sample status"),
    }
    value = SampleIdentity(**payload, fingerprint=_fingerprint("sample-identity-v1", payload))
    validate_sample_identity(value)
    return value


def build_dataset_identity(
    *,
    dataset_identity: str,
    dataset_fingerprint: str,
    source_fingerprints: Sequence[str],
    data_basis_status: str,
    survivorship_status: str,
    security_identity_status: str,
    point_in_time_universe_status: str,
    historically_robust: bool = False,
) -> DatasetIdentity:
    statuses = (
        data_basis_status,
        survivorship_status,
        security_identity_status,
        point_in_time_universe_status,
    )
    if any(item not in DATA_STATUS_VALUES for item in statuses):
        raise ResearchGovernanceError("Dataset admission status is unsupported.")
    if historically_robust and statuses != (VERIFIED, CONTROLLED, VERIFIED, VERIFIED):
        raise ResearchGovernanceError(
            "Historically robust data requires verified basis, security identity, and "
            "point-in-time universe plus controlled survivorship."
        )
    payload = {
        "dataset_identity": _token(dataset_identity, "Dataset identity"),
        "dataset_fingerprint": _sha256(dataset_fingerprint, "Dataset fingerprint"),
        "source_fingerprints": _sha256_values(
            source_fingerprints, "Dataset source fingerprints"
        ),
        "data_basis_status": data_basis_status,
        "survivorship_status": survivorship_status,
        "security_identity_status": security_identity_status,
        "point_in_time_universe_status": point_in_time_universe_status,
        "historically_robust": bool(historically_robust),
    }
    value = DatasetIdentity(**payload, fingerprint=_fingerprint("dataset-identity-v1", payload))
    validate_dataset_identity(value)
    return value


def build_data_partition(
    *,
    role: str,
    starts_at: datetime,
    ends_at: datetime,
    sample: SampleIdentity,
    dataset: DatasetIdentity,
) -> DataPartition:
    validate_sample_identity(sample)
    validate_dataset_identity(dataset)
    if role not in PARTITION_ROLES:
        raise ResearchGovernanceError("Data partition role is unsupported.")
    start = _aware(starts_at, "Partition start")
    end = _aware(ends_at, "Partition end")
    if end <= start:
        raise ResearchGovernanceError("Data partition end must follow its start.")
    payload = {
        "role": role,
        "starts_at": _iso(start),
        "ends_at": _iso(end),
        "sample_identity": sample.sample_identity,
        "sample_fingerprint": sample.fingerprint,
        "dataset_identity": dataset.dataset_identity,
        "dataset_fingerprint": dataset.fingerprint,
    }
    value = DataPartition(**payload, fingerprint=_fingerprint("data-partition-v1", payload))
    validate_data_partition(value)
    return value


def build_metric_definition(
    *,
    metric_id: str,
    metric_version: str,
    semantic_description: str,
    formula: str,
    direction: str,
    role: str,
) -> MetricDefinition:
    if role not in {PREREGISTERED_PRIMARY, PREREGISTERED_SECONDARY}:
        raise ResearchGovernanceError("Metric definition role must be preregistered.")
    payload = {
        "metric_id": _token(metric_id, "Metric ID"),
        "metric_version": _token(metric_version, "Metric version"),
        "semantic_description": _text(semantic_description, "Metric description"),
        "formula": _text(formula, "Metric formula"),
        "direction": _token(direction, "Metric direction"),
        "role": role,
    }
    value = MetricDefinition(**payload, fingerprint=_fingerprint("metric-definition-v1", payload))
    validate_metric_definition(value)
    return value


def build_benchmark_definition(
    *,
    benchmark_id: str,
    benchmark_version: str,
    semantic_description: str,
    source_identity: str,
) -> BenchmarkDefinition:
    payload = {
        "benchmark_id": _token(benchmark_id, "Benchmark ID"),
        "benchmark_version": _token(benchmark_version, "Benchmark version"),
        "semantic_description": _text(semantic_description, "Benchmark description"),
        "source_identity": _token(source_identity, "Benchmark source identity"),
    }
    value = BenchmarkDefinition(
        **payload, fingerprint=_fingerprint("benchmark-definition-v1", payload)
    )
    validate_benchmark_definition(value)
    return value


def build_criterion_definition(
    *,
    criterion_id: str,
    criterion_kind: str,
    metric_id: str,
    comparator: str,
    threshold: float,
    semantic_description: str,
) -> CriterionDefinition:
    if criterion_kind not in {"SUCCESS", "FAILURE"}:
        raise ResearchGovernanceError("Criterion kind must be SUCCESS or FAILURE.")
    value_threshold = _finite(threshold, "Criterion threshold")
    payload = {
        "criterion_id": _token(criterion_id, "Criterion ID"),
        "criterion_kind": criterion_kind,
        "metric_id": _token(metric_id, "Criterion metric ID"),
        "comparator": _token(comparator, "Criterion comparator"),
        "threshold": value_threshold,
        "semantic_description": _text(semantic_description, "Criterion description"),
    }
    value = CriterionDefinition(
        **payload, fingerprint=_fingerprint("criterion-definition-v1", payload)
    )
    validate_criterion_definition(value)
    return value


def build_parameter_space(
    *, parameter_name: str, allowed_values: Sequence[str]
) -> ParameterSpace:
    payload = {
        "parameter_name": _token(parameter_name, "Parameter name"),
        "allowed_values": _tokens(allowed_values, "Allowed parameter values"),
    }
    value = ParameterSpace(**payload, fingerprint=_fingerprint("parameter-space-v1", payload))
    validate_parameter_space(value)
    return value


def build_parameter_search_policy(
    *,
    search_method: str,
    planned_variant_count: int,
    parameter_space: Sequence[ParameterSpace],
    allowed_feature_set_fingerprints: Sequence[str],
    allowed_model_families: Sequence[str],
    planned_metric_count: int,
    planned_feature_set_count: int,
) -> ParameterSearchPolicy:
    if search_method not in SEARCH_METHODS:
        raise ResearchGovernanceError("Parameter-search method is unsupported.")
    payload = {
        "search_method": search_method,
        "planned_variant_count": _positive_int(
            planned_variant_count, "Planned variant count"
        ),
        "parameter_space": tuple(sorted(parameter_space, key=lambda item: item.parameter_name)),
        "allowed_feature_set_fingerprints": _sha256_values(
            allowed_feature_set_fingerprints, "Allowed feature-set fingerprints"
        ),
        "allowed_model_families": _tokens(
            allowed_model_families, "Allowed model families"
        ),
        "planned_metric_count": _positive_int(
            planned_metric_count, "Planned metric count"
        ),
        "planned_feature_set_count": _positive_int(
            planned_feature_set_count, "Planned feature-set count"
        ),
    }
    for item in payload["parameter_space"]:
        validate_parameter_space(item)
    value = ParameterSearchPolicy(
        **payload, fingerprint=_fingerprint("parameter-search-policy-v1", payload)
    )
    validate_parameter_search_policy(value)
    return value


def build_holdout_policy(
    *,
    initial_state: str,
    holdout_identity: str | None = None,
    final_access_not_before: datetime | None = None,
    final_access_gate: str | None = None,
) -> HoldoutPolicy:
    if initial_state not in {SEALED, NOT_APPLICABLE}:
        raise ResearchGovernanceError("Initial holdout state must be SEALED or NOT_APPLICABLE.")
    if initial_state == SEALED:
        identity = _sha256(holdout_identity, "Holdout identity")
        gate_time = _iso(_aware(final_access_not_before, "Holdout final-access time"))
        gate = _text(final_access_gate, "Holdout final-access gate")
    else:
        if any(value is not None for value in (holdout_identity, final_access_not_before, final_access_gate)):
            raise ResearchGovernanceError("Not-applicable holdout cannot define an access gate.")
        identity = None
        gate_time = None
        gate = None
    payload = {
        "initial_state": initial_state,
        "holdout_identity": identity,
        "final_access_not_before": gate_time,
        "final_access_gate": gate,
    }
    value = HoldoutPolicy(**payload, fingerprint=_fingerprint("holdout-policy-v1", payload))
    validate_holdout_policy(value)
    return value


def build_research_experiment(
    *,
    experiment_id: str,
    experiment_version: str,
    title: str,
    research_question: str,
    hypothesis: str,
    created_at: datetime,
    preregistered_at: datetime,
    research_domain: str,
    research_timing: str,
    research_intent: str,
    code_git_identity: str,
    policy_fingerprint: str,
    input_sample_identities: Sequence[SampleIdentity],
    input_dataset_identities: Sequence[DatasetIdentity],
    feature_definitions: Sequence[FeatureDefinition],
    metric_definitions: Sequence[MetricDefinition],
    benchmark_definition: BenchmarkDefinition,
    success_criteria: Sequence[CriterionDefinition],
    failure_criteria: Sequence[CriterionDefinition],
    data_partitions: Sequence[DataPartition],
    holdout_policy: HoldoutPolicy,
    parameter_search_policy: ParameterSearchPolicy,
    planned_minimum_sample: int,
    require_independent_partitions: bool = True,
) -> ResearchExperiment:
    created = _aware(created_at, "Experiment creation time")
    preregistered = _aware(preregistered_at, "Experiment preregistration time")
    if preregistered < created:
        raise ResearchGovernanceError("Experiment cannot be preregistered before creation.")
    if research_timing not in RESEARCH_TIMINGS:
        raise ResearchGovernanceError("Research timing is unsupported.")
    if research_intent not in RESEARCH_INTENTS:
        raise ResearchGovernanceError("Research intent is unsupported.")
    payload = {
        "contract_version": CONTRACT_VERSION,
        "profile": REGISTRY_PROFILE,
        "experiment_id": _token(experiment_id, "Experiment ID"),
        "experiment_version": _token(experiment_version, "Experiment version"),
        "title": _text(title, "Experiment title"),
        "research_question": _text(research_question, "Research question"),
        "hypothesis": _text(hypothesis, "Hypothesis"),
        "created_at": _iso(created),
        "preregistered_at": _iso(preregistered),
        "research_domain": _token(research_domain, "Research domain"),
        "research_timing": research_timing,
        "research_intent": research_intent,
        "code_git_identity": _git_sha(code_git_identity, "Experiment Git identity"),
        "policy_fingerprint": _sha256(policy_fingerprint, "Experiment policy fingerprint"),
        "input_sample_identities": tuple(
            sorted(input_sample_identities, key=lambda item: item.sample_identity)
        ),
        "input_dataset_identities": tuple(
            sorted(input_dataset_identities, key=lambda item: item.dataset_identity)
        ),
        "feature_definitions": tuple(
            sorted(feature_definitions, key=lambda item: (item.feature_id, item.feature_version))
        ),
        "metric_definitions": tuple(
            sorted(metric_definitions, key=lambda item: (item.metric_id, item.metric_version))
        ),
        "benchmark_definition": benchmark_definition,
        "success_criteria": tuple(sorted(success_criteria, key=lambda item: item.criterion_id)),
        "failure_criteria": tuple(sorted(failure_criteria, key=lambda item: item.criterion_id)),
        "data_partitions": tuple(sorted(data_partitions, key=lambda item: item.role)),
        "require_independent_partitions": bool(require_independent_partitions),
        "holdout_policy": holdout_policy,
        "parameter_search_policy": parameter_search_policy,
        "planned_minimum_sample": _positive_int(
            planned_minimum_sample, "Planned minimum sample"
        ),
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
        "status": PREREGISTERED,
    }
    value = ResearchExperiment(
        **payload, fingerprint=_fingerprint("research-experiment-v1", payload)
    )
    validate_research_experiment(value)
    return value


@dataclass(frozen=True)
class ExperimentAmendment:
    contract_version: int
    amendment_id: str
    experiment_id: str
    experiment_fingerprint: str
    amendment_time: str
    reason: str
    changed_fields: tuple[str, ...]
    prior_fingerprint: str
    new_fingerprint: str
    outcome_knowledge_status: str
    fingerprint: str


@dataclass(frozen=True)
class ExperimentVariant:
    contract_version: int
    experiment_id: str
    experiment_fingerprint: str
    variant_id: str
    parameter_values: tuple[tuple[str, str], ...]
    feature_set_identity: str
    feature_set_fingerprint: str
    model_identity: str
    created_at: str
    evaluated_at: str | None
    data_identity: str
    data_fingerprint: str
    code_identity: str
    search_space_status: str
    result_identity: str | None
    status: str
    status_reason: str | None
    fingerprint: str


@dataclass(frozen=True)
class HoldoutAccessReceipt:
    contract_version: int
    receipt_id: str
    experiment_id: str
    experiment_fingerprint: str
    holdout_identity: str
    accessed_at: str
    reason: str
    authorization_state: str
    prior_access_count: int
    prior_receipt_fingerprint: str | None
    resulting_holdout_state: str
    fingerprint: str


@dataclass(frozen=True)
class MetricObservation:
    metric_id: str
    metric_version: str
    metric_definition_fingerprint: str
    metric_role: str
    value: float | None
    status: str
    fingerprint: str


@dataclass(frozen=True)
class ExperimentResult:
    contract_version: int
    result_id: str
    experiment_id: str
    experiment_fingerprint: str
    variant_id: str
    variant_fingerprint: str
    evaluated_at: str
    research_timing: str
    research_intent: str
    input_data_fingerprint: str
    partition_fingerprints: tuple[str, ...]
    metrics: tuple[MetricObservation, ...]
    benchmark_metrics: tuple[MetricObservation, ...]
    conclusion: str
    limitations: tuple[str, ...]
    holdout_state: str
    holdout_access_receipt_fingerprints: tuple[str, ...]
    actual_sample: int
    actual_variant_count: int
    actual_metric_count: int
    actual_feature_set_count: int
    selection_occurred: bool
    authority: str
    execution_authority: str
    result_fingerprint: str


@dataclass(frozen=True)
class ExperimentInvalidation:
    contract_version: int
    invalidation_id: str
    experiment_id: str
    experiment_fingerprint: str
    invalidation_reason: str
    invalidated_at: str
    evidence_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class ModelHealthMetricDefinition:
    metric_id: str
    metric_version: str
    semantic_description: str
    formula: str
    failure_comparator: str
    failure_threshold: float
    fingerprint: str


@dataclass(frozen=True)
class ModelHealthPolicy:
    contract_version: int
    policy_id: str
    policy_version: str
    evidence_window: str
    minimum_sample: int
    benchmark_identity: str
    benchmark_fingerprint: str
    health_metrics: tuple[ModelHealthMetricDefinition, ...]
    failure_threshold_policy: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ModelHealthRecord:
    contract_version: int
    record_id: str
    model_identity: str
    model_version: str
    evaluated_at: str
    evidence_window: str
    sample_size: int
    benchmark_identity: str
    benchmark_fingerprint: str
    health_policy_id: str
    health_policy_fingerprint: str
    health_metrics: tuple[MetricObservation, ...]
    health_state: str
    reason_codes: tuple[str, ...]
    evidence_kind: str
    evidence_fingerprint: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class RegistrySnapshot:
    experiments: tuple[ResearchExperiment, ...] = ()
    amendments: tuple[ExperimentAmendment, ...] = ()
    variants: tuple[ExperimentVariant, ...] = ()
    results: tuple[ExperimentResult, ...] = ()
    holdout_access: tuple[HoldoutAccessReceipt, ...] = ()
    invalidations: tuple[ExperimentInvalidation, ...] = ()
    model_health_policies: tuple[ModelHealthPolicy, ...] = ()
    model_health_records: tuple[ModelHealthRecord, ...] = ()


@dataclass(frozen=True)
class RegistrySummary:
    experiments_registered: int
    prospective: int
    retrospective: int
    exploratory: int
    confirmatory: int
    variants_attempted: int
    variants_valid: int
    variants_invalid: int
    variant_status_counts: tuple[tuple[str, int], ...]
    result_conclusion_counts: tuple[tuple[str, int], ...]
    sealed_holdouts: int
    opened_holdouts: int
    contaminated_holdouts: int
    not_applicable_holdouts: int
    model_health_state_counts: tuple[tuple[str, int], ...]
    planned_variant_count: int
    planned_metric_count: int
    planned_feature_set_count: int
    actual_metric_count: int
    actual_feature_set_count: int
    selection_occurred_count: int


@dataclass(frozen=True)
class SpecialistFixtureMetadata:
    specialist_id: str
    specialist_version: str
    specialist_policy_id: str
    specialist_policy_fingerprint: str
    source_branch: str
    source_commit: str
    experiment_id: str
    research_question: str
    status: str
    fingerprint: str


@dataclass(frozen=True)
class StatDataCompatibility:
    contract_version: int
    source_branch: str
    source_commit: str
    sample_identity: str
    policy_id: str
    policy_fingerprint: str
    sample_status: str
    sessions: int
    opportunities: int
    import_mode: str
    compatible: bool
    fingerprint: str


@dataclass(frozen=True)
class ResearchDataCompatibility:
    source_branch: str
    source_commit: str
    report_fingerprint: str
    classification: str
    data_basis_status: str
    survivorship_status: str
    security_identity_status: str
    point_in_time_universe_status: str
    historically_robust: bool
    fingerprint: str


def build_experiment_amendment(
    *,
    experiment: ResearchExperiment,
    amendment_id: str,
    amendment_time: str,
    reason: str,
    changed_fields: Sequence[str],
    new_fingerprint: str,
    outcome_knowledge_status: str,
    first_outcome_time: str | None = None,
) -> ExperimentAmendment:
    validate_research_experiment(experiment)
    amendment_time_value = _timestamp(amendment_time, "Amendment time")
    if _parse_timestamp(amendment_time_value) < _parse_timestamp(
        experiment.preregistered_at
    ):
        raise ResearchGovernanceError("Amendment cannot precede preregistration")
    outcome_status = _choice(
        outcome_knowledge_status,
        OUTCOME_KNOWLEDGE_STATES,
        "Outcome knowledge status",
    )
    if first_outcome_time is not None:
        first_outcome = _timestamp(first_outcome_time, "First outcome time")
        if _parse_timestamp(amendment_time_value) >= _parse_timestamp(first_outcome):
            if outcome_status != POST_OUTCOME_AMENDMENT:
                raise ResearchGovernanceError(
                    "An amendment at or after first outcome knowledge must be post-outcome"
                )
        elif outcome_status != PRE_OUTCOME_AMENDMENT:
            raise ResearchGovernanceError(
                "An amendment before first outcome knowledge must be pre-outcome"
            )
    payload = {
        "contract_version": CONTRACT_VERSION,
        "amendment_id": _token(amendment_id, "Amendment ID"),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint,
        "amendment_time": amendment_time_value,
        "reason": _text(reason, "Amendment reason"),
        "changed_fields": _tokens(changed_fields, "Changed fields"),
        "prior_fingerprint": experiment.fingerprint,
        "new_fingerprint": _sha256(new_fingerprint, "Amended definition fingerprint"),
        "outcome_knowledge_status": outcome_status,
    }
    value = ExperimentAmendment(
        **payload, fingerprint=_fingerprint("experiment-amendment-v1", payload)
    )
    validate_experiment_amendment(value)
    return value


def build_experiment_variant(
    *,
    experiment: ResearchExperiment,
    variant_id: str,
    parameter_values: Mapping[str, Any],
    feature_set_identity: str,
    feature_set_fingerprint: str,
    model_identity: str,
    created_at: str,
    evaluated_at: str | None,
    data_identity: str,
    data_fingerprint: str,
    code_identity: str,
    result_identity: str | None,
    status: str,
    status_reason: str | None = None,
) -> ExperimentVariant:
    validate_research_experiment(experiment)
    normalized_parameters = tuple(
        sorted(
            (
                _token(str(name), "Parameter name"),
                _scalar_text(value, f"Parameter {name}"),
            )
            for name, value in parameter_values.items()
        )
    )
    if not normalized_parameters and experiment.parameter_search_policy.parameter_space:
        raise ResearchGovernanceError("Variant parameter values are required")
    expected_spaces = {
        item.parameter_name: set(item.allowed_values)
        for item in experiment.parameter_search_policy.parameter_space
    }
    supplied = dict(normalized_parameters)
    within_space = set(supplied) == set(expected_spaces) and all(
        supplied[name] in values for name, values in expected_spaces.items()
    )
    feature_fingerprint = _sha256(
        feature_set_fingerprint, "Variant feature-set fingerprint"
    )
    within_space = within_space and feature_fingerprint in set(
        experiment.parameter_search_policy.allowed_feature_set_fingerprints
    )
    within_space = within_space and _token(
        model_identity, "Variant model identity"
    ) in set(experiment.parameter_search_policy.allowed_model_families)
    variant_status = _choice(status, VARIANT_STATUSES, "Variant status")
    search_status = (
        WITHIN_PREREGISTERED_SPACE if within_space else UNPLANNED_SEARCH_EXPANSION
    )
    if not within_space and variant_status != INVALID:
        raise ResearchGovernanceError(
            "A variant outside the preregistered search space must be recorded as invalid"
        )
    created_value = _timestamp(created_at, "Variant created time")
    if _parse_timestamp(created_value) < _parse_timestamp(experiment.preregistered_at):
        raise ResearchGovernanceError("Variant cannot precede preregistration")
    evaluated_value = (
        None if evaluated_at is None else _timestamp(evaluated_at, "Variant evaluated time")
    )
    if evaluated_value and _parse_timestamp(evaluated_value) < _parse_timestamp(created_value):
        raise ResearchGovernanceError("Variant evaluation cannot precede creation")
    if variant_status in {EVALUATED, NULL_RESULT} and (
        evaluated_value is None or result_identity is None
    ):
        raise ResearchGovernanceError(
            "An evaluated or null variant requires evaluation and result identities"
        )
    if variant_status in {FAILED, INVALID, ABANDONED_WITH_REASON} and not status_reason:
        raise ResearchGovernanceError("A failed, invalid, or abandoned variant needs a reason")
    data_fingerprint_value = _sha256(data_fingerprint, "Variant data fingerprint")
    if not any(
        data_fingerprint_value in {item.fingerprint, item.dataset_fingerprint}
        for item in experiment.input_dataset_identities
    ):
        raise ResearchGovernanceError("Variant data identity is not registered by experiment")
    code_value = _git_sha(code_identity, "Variant code identity")
    if code_value != experiment.code_git_identity:
        raise ResearchGovernanceError("Variant code identity differs from experiment")
    payload = {
        "contract_version": CONTRACT_VERSION,
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint,
        "variant_id": _token(variant_id, "Variant ID"),
        "parameter_values": normalized_parameters,
        "feature_set_identity": _token(feature_set_identity, "Feature-set identity"),
        "feature_set_fingerprint": feature_fingerprint,
        "model_identity": _token(model_identity, "Variant model identity"),
        "created_at": created_value,
        "evaluated_at": evaluated_value,
        "data_identity": _token(data_identity, "Variant data identity"),
        "data_fingerprint": data_fingerprint_value,
        "code_identity": code_value,
        "search_space_status": search_status,
        "result_identity": (
            None if result_identity is None else _token(result_identity, "Result identity")
        ),
        "status": variant_status,
        "status_reason": None if status_reason is None else _text(status_reason, "Status reason"),
    }
    value = ExperimentVariant(
        **payload, fingerprint=_fingerprint("experiment-variant-v1", payload)
    )
    validate_experiment_variant(value)
    return value


def build_holdout_access_receipt(
    *,
    experiment: ResearchExperiment,
    receipt_id: str,
    accessed_at: str,
    reason: str,
    authorization_state: str,
    prior_receipts: Sequence[HoldoutAccessReceipt] = (),
) -> HoldoutAccessReceipt:
    validate_research_experiment(experiment)
    policy = experiment.holdout_policy
    if policy.initial_state == NOT_APPLICABLE or policy.holdout_identity is None:
        raise ResearchGovernanceError("Experiment has no accessible holdout")
    ordered = sorted(prior_receipts, key=lambda item: item.prior_access_count)
    for index, receipt in enumerate(ordered):
        validate_holdout_access_receipt(receipt)
        if receipt.experiment_fingerprint != experiment.fingerprint:
            raise ResearchGovernanceError("Prior receipt belongs to another experiment")
        if receipt.prior_access_count != index:
            raise ResearchGovernanceError("Holdout access receipt history is incomplete")
    access_time = _timestamp(accessed_at, "Holdout access time")
    if _parse_timestamp(access_time) < _parse_timestamp(experiment.preregistered_at):
        raise ResearchGovernanceError("Holdout access cannot precede preregistration")
    if ordered and _parse_timestamp(access_time) <= _parse_timestamp(ordered[-1].accessed_at):
        raise ResearchGovernanceError("Holdout access time must advance")
    authorization = _choice(
        authorization_state, HOLDOUT_AUTHORIZATION_STATES, "Holdout authorization state"
    )
    already_contaminated = bool(
        ordered
        and ordered[-1].resulting_holdout_state == CONTAMINATED_BY_EARLY_ACCESS
    )
    if already_contaminated:
        resulting_state = CONTAMINATED_BY_EARLY_ACCESS
    elif authorization == FINAL_EVALUATION_AUTHORIZED:
        if policy.final_access_not_before and _parse_timestamp(access_time) < _parse_timestamp(
            policy.final_access_not_before
        ):
            resulting_state = CONTAMINATED_BY_EARLY_ACCESS
        else:
            resulting_state = OPENED_FOR_FINAL_EVALUATION
    else:
        resulting_state = CONTAMINATED_BY_EARLY_ACCESS
    payload = {
        "contract_version": CONTRACT_VERSION,
        "receipt_id": _token(receipt_id, "Holdout receipt ID"),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint,
        "holdout_identity": policy.holdout_identity,
        "accessed_at": access_time,
        "reason": _text(reason, "Holdout access reason"),
        "authorization_state": authorization,
        "prior_access_count": len(ordered),
        "prior_receipt_fingerprint": ordered[-1].fingerprint if ordered else None,
        "resulting_holdout_state": resulting_state,
    }
    value = HoldoutAccessReceipt(
        **payload, fingerprint=_fingerprint("holdout-access-receipt-v1", payload)
    )
    validate_holdout_access_receipt(value)
    return value


def build_metric_observation(
    *,
    definition: MetricDefinition,
    value: float | None,
    status: str = "OBSERVED",
    metric_role: str | None = None,
) -> MetricObservation:
    validate_metric_definition(definition)
    role = definition.role if metric_role is None else _choice(
        metric_role, METRIC_ROLES, "Metric observation role"
    )
    numeric = _finite_number(value, "Metric value", allow_none=True)
    payload = {
        "metric_id": definition.metric_id,
        "metric_version": definition.metric_version,
        "metric_definition_fingerprint": definition.fingerprint,
        "metric_role": role,
        "value": numeric,
        "status": _token(status, "Metric status"),
    }
    value_record = MetricObservation(
        **payload, fingerprint=_fingerprint("metric-observation-v1", payload)
    )
    validate_metric_observation(value_record)
    return value_record


def build_experiment_result(
    *,
    experiment: ResearchExperiment,
    variant: ExperimentVariant,
    evaluated_at: str,
    input_data_fingerprint: str,
    partition_fingerprints: Sequence[str],
    metrics: Sequence[MetricObservation],
    benchmark_metrics: Sequence[MetricObservation],
    conclusion: str,
    limitations: Sequence[str],
    holdout_state: str,
    holdout_access_receipts: Sequence[HoldoutAccessReceipt],
    actual_sample: int,
    actual_variant_count: int,
    actual_metric_count: int,
    actual_feature_set_count: int,
    selection_occurred: bool,
) -> ExperimentResult:
    validate_research_experiment(experiment)
    validate_experiment_variant(variant)
    if variant.experiment_fingerprint != experiment.fingerprint:
        raise ResearchGovernanceError("Result variant belongs to another experiment")
    if not variant.result_identity:
        raise ResearchGovernanceError("Result variant has no registered result identity")
    result_conclusion = _choice(conclusion, RESULT_CONCLUSIONS, "Result conclusion")
    sample_count = _nonnegative_int(actual_sample, "Actual sample")
    if sample_count < experiment.planned_minimum_sample and result_conclusion not in {
        INSUFFICIENT_SAMPLE,
        INVALID_DATA,
        INVALID_EXPERIMENT,
        HOLDOUT_CONTAMINATED,
        ABANDONED_WITH_REASON,
    }:
        raise ResearchGovernanceError(
            "A sample below the preregistered minimum cannot have a conclusive result"
        )
    experiment_metrics = {
        (item.metric_id, item.metric_version): item
        for item in experiment.metric_definitions
    }
    for observation in tuple(metrics) + tuple(benchmark_metrics):
        validate_metric_observation(observation)
        key = (observation.metric_id, observation.metric_version)
        if observation.metric_role == PREREGISTERED_PRIMARY:
            expected = experiment_metrics.get(key)
            if expected is None or expected.fingerprint != observation.metric_definition_fingerprint:
                raise ResearchGovernanceError(
                    "A primary result metric must match the preregistered definition"
                )
    registered_partitions = {item.fingerprint for item in experiment.data_partitions}
    result_partitions = _sha256_values(partition_fingerprints, "Result partitions")
    if not set(result_partitions).issubset(registered_partitions):
        raise ResearchGovernanceError("Result references an unregistered data partition")
    receipts = tuple(sorted(holdout_access_receipts, key=lambda item: item.prior_access_count))
    for receipt in receipts:
        validate_holdout_access_receipt(receipt)
        if receipt.experiment_fingerprint != experiment.fingerprint:
            raise ResearchGovernanceError("Result holdout receipt belongs to another experiment")
    derived_holdout_state = _derive_holdout_state(experiment, receipts)
    requested_holdout_state = _choice(holdout_state, HOLDOUT_STATES, "Result holdout state")
    if requested_holdout_state != derived_holdout_state:
        raise ResearchGovernanceError("Result holdout state contradicts access history")
    if derived_holdout_state == CONTAMINATED_BY_EARLY_ACCESS and result_conclusion != HOLDOUT_CONTAMINATED:
        raise ResearchGovernanceError("A contaminated holdout requires contaminated conclusion")
    evaluated_value = _timestamp(evaluated_at, "Result evaluation time")
    if _parse_timestamp(evaluated_value) < _parse_timestamp(experiment.preregistered_at):
        raise ResearchGovernanceError("Result cannot precede preregistration")
    if variant.evaluated_at is None or _parse_timestamp(evaluated_value) < _parse_timestamp(
        variant.evaluated_at
    ):
        raise ResearchGovernanceError("Result cannot precede variant evaluation")
    if any(
        _parse_timestamp(receipt.accessed_at) > _parse_timestamp(evaluated_value)
        for receipt in receipts
    ):
        raise ResearchGovernanceError("Result cannot cite future holdout access")
    if variant.status == NULL_RESULT and result_conclusion in {SUPPORTED, NOT_SUPPORTED}:
        raise ResearchGovernanceError("A null variant cannot claim a conclusive result")
    payload = {
        "contract_version": CONTRACT_VERSION,
        "result_id": variant.result_identity,
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint,
        "variant_id": variant.variant_id,
        "variant_fingerprint": variant.fingerprint,
        "evaluated_at": evaluated_value,
        "research_timing": experiment.research_timing,
        "research_intent": experiment.research_intent,
        "input_data_fingerprint": _sha256(
            input_data_fingerprint, "Result input-data fingerprint"
        ),
        "partition_fingerprints": result_partitions,
        "metrics": tuple(sorted(metrics, key=lambda item: (item.metric_id, item.metric_version))),
        "benchmark_metrics": tuple(
            sorted(benchmark_metrics, key=lambda item: (item.metric_id, item.metric_version))
        ),
        "conclusion": result_conclusion,
        "limitations": _texts(limitations, "Result limitations", allow_empty=True),
        "holdout_state": requested_holdout_state,
        "holdout_access_receipt_fingerprints": tuple(item.fingerprint for item in receipts),
        "actual_sample": sample_count,
        "actual_variant_count": _positive_int(actual_variant_count, "Actual variant count"),
        "actual_metric_count": _positive_int(actual_metric_count, "Actual metric count"),
        "actual_feature_set_count": _positive_int(
            actual_feature_set_count, "Actual feature-set count"
        ),
        "selection_occurred": bool(selection_occurred),
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    value = ExperimentResult(
        **payload, result_fingerprint=_fingerprint("experiment-result-v1", payload)
    )
    validate_experiment_result(value)
    return value


def build_experiment_invalidation(
    *,
    experiment: ResearchExperiment,
    invalidation_id: str,
    invalidation_reason: str,
    invalidated_at: str,
    evidence_fingerprint: str,
) -> ExperimentInvalidation:
    validate_research_experiment(experiment)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "invalidation_id": _token(invalidation_id, "Invalidation ID"),
        "experiment_id": experiment.experiment_id,
        "experiment_fingerprint": experiment.fingerprint,
        "invalidation_reason": _text(invalidation_reason, "Invalidation reason"),
        "invalidated_at": _timestamp(invalidated_at, "Invalidation time"),
        "evidence_fingerprint": _sha256(
            evidence_fingerprint, "Invalidation evidence fingerprint"
        ),
    }
    value = ExperimentInvalidation(
        **payload, fingerprint=_fingerprint("experiment-invalidation-v1", payload)
    )
    validate_experiment_invalidation(value)
    return value


def build_model_health_metric_definition(
    *,
    metric_id: str,
    metric_version: str,
    semantic_description: str,
    formula: str,
    failure_comparator: str,
    failure_threshold: float,
) -> ModelHealthMetricDefinition:
    payload = {
        "metric_id": _token(metric_id, "Health metric ID"),
        "metric_version": _token(metric_version, "Health metric version"),
        "semantic_description": _text(
            semantic_description, "Health metric description"
        ),
        "formula": _text(formula, "Health metric formula"),
        "failure_comparator": _choice(
            failure_comparator, {"LT", "LTE", "GT", "GTE", "EQ"}, "Health comparator"
        ),
        "failure_threshold": _finite_number(
            failure_threshold, "Health failure threshold"
        ),
    }
    value = ModelHealthMetricDefinition(
        **payload, fingerprint=_fingerprint("model-health-metric-v1", payload)
    )
    validate_model_health_metric_definition(value)
    return value


def build_model_health_policy(
    *,
    policy_id: str,
    policy_version: str,
    evidence_window: str,
    minimum_sample: int,
    benchmark: BenchmarkDefinition,
    health_metrics: Sequence[ModelHealthMetricDefinition],
    failure_threshold_policy: str,
) -> ModelHealthPolicy:
    validate_benchmark_definition(benchmark)
    for metric in health_metrics:
        validate_model_health_metric_definition(metric)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "policy_id": _token(policy_id, "Health policy ID"),
        "policy_version": _token(policy_version, "Health policy version"),
        "evidence_window": _text(evidence_window, "Health evidence window"),
        "minimum_sample": _positive_int(minimum_sample, "Health minimum sample"),
        "benchmark_identity": benchmark.benchmark_id,
        "benchmark_fingerprint": benchmark.fingerprint,
        "health_metrics": tuple(
            sorted(health_metrics, key=lambda item: (item.metric_id, item.metric_version))
        ),
        "failure_threshold_policy": _text(
            failure_threshold_policy, "Health threshold policy"
        ),
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    value = ModelHealthPolicy(
        **payload, fingerprint=_fingerprint("model-health-policy-v1", payload)
    )
    validate_model_health_policy(value)
    return value


def build_model_health_metric_observation(
    *,
    definition: ModelHealthMetricDefinition,
    value: float | None,
    status: str = "OBSERVED",
) -> MetricObservation:
    validate_model_health_metric_definition(definition)
    payload = {
        "metric_id": definition.metric_id,
        "metric_version": definition.metric_version,
        "metric_definition_fingerprint": definition.fingerprint,
        "metric_role": PREREGISTERED_PRIMARY,
        "value": _finite_number(value, "Health metric value", allow_none=True),
        "status": _token(status, "Health metric status"),
    }
    observation = MetricObservation(
        **payload, fingerprint=_fingerprint("metric-observation-v1", payload)
    )
    validate_metric_observation(observation)
    return observation


def build_model_health_record(
    *,
    policy: ModelHealthPolicy,
    record_id: str,
    model_identity: str,
    model_version: str,
    evaluated_at: str,
    sample_size: int,
    health_metrics: Sequence[MetricObservation],
    health_state: str,
    reason_codes: Sequence[str],
    evidence_kind: str,
    evidence_fingerprint: str,
) -> ModelHealthRecord:
    validate_model_health_policy(policy)
    state = _choice(health_state, MODEL_HEALTH_STATES, "Model-health state")
    kind = _choice(evidence_kind, HEALTH_EVIDENCE_KINDS, "Health evidence kind")
    count = _nonnegative_int(sample_size, "Model-health sample size")
    if state == HEALTHY and kind in {UNIT_TEST_ONLY, SYNTHETIC_EVIDENCE}:
        raise ResearchGovernanceError("Synthetic or unit-test evidence cannot prove health")
    if state == HEALTHY and count < policy.minimum_sample:
        raise ResearchGovernanceError("Insufficient sample cannot be labeled healthy")
    allowed_metric_fingerprints = {item.fingerprint for item in policy.health_metrics}
    for metric in health_metrics:
        validate_metric_observation(metric)
        if metric.metric_definition_fingerprint not in allowed_metric_fingerprints:
            raise ResearchGovernanceError("Health record uses a metric outside its policy")
    payload = {
        "contract_version": CONTRACT_VERSION,
        "record_id": _token(record_id, "Health record ID"),
        "model_identity": _token(model_identity, "Health model identity"),
        "model_version": _token(model_version, "Health model version"),
        "evaluated_at": _timestamp(evaluated_at, "Health evaluation time"),
        "evidence_window": policy.evidence_window,
        "sample_size": count,
        "benchmark_identity": policy.benchmark_identity,
        "benchmark_fingerprint": policy.benchmark_fingerprint,
        "health_policy_id": policy.policy_id,
        "health_policy_fingerprint": policy.fingerprint,
        "health_metrics": tuple(
            sorted(health_metrics, key=lambda item: (item.metric_id, item.metric_version))
        ),
        "health_state": state,
        "reason_codes": _tokens(reason_codes, "Health reason codes", allow_empty=True),
        "evidence_kind": kind,
        "evidence_fingerprint": _sha256(evidence_fingerprint, "Health evidence fingerprint"),
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    value = ModelHealthRecord(
        **payload, fingerprint=_fingerprint("model-health-record-v1", payload)
    )
    validate_model_health_record(value)
    return value


def validate_feature_definition(value: FeatureDefinition) -> None:
    _validate_fingerprint(value, "fingerprint", "feature-definition-v1")
    _tokens(value.inputs, "Feature inputs")


def validate_sample_identity(value: SampleIdentity) -> None:
    _validate_fingerprint(value, "fingerprint", "sample-identity-v1")
    _sha256(value.policy_fingerprint, "Sample policy fingerprint")


def validate_dataset_identity(value: DatasetIdentity) -> None:
    _validate_fingerprint(value, "fingerprint", "dataset-identity-v1")
    statuses = (
        value.data_basis_status,
        value.survivorship_status,
        value.security_identity_status,
        value.point_in_time_universe_status,
    )
    if any(item not in DATA_STATUS_VALUES for item in statuses):
        raise ResearchGovernanceError("Dataset admission status is unsupported")
    if value.historically_robust and statuses != (
        VERIFIED,
        CONTROLLED,
        VERIFIED,
        VERIFIED,
    ):
        raise ResearchGovernanceError("Historically robust claim is unsupported by data")


def validate_data_partition(value: DataPartition) -> None:
    _validate_fingerprint(value, "fingerprint", "data-partition-v1")
    _choice(value.role, PARTITION_ROLES, "Partition role")
    if _parse_timestamp(value.ends_at) <= _parse_timestamp(value.starts_at):
        raise ResearchGovernanceError("Partition end must follow start")


def validate_metric_definition(value: MetricDefinition) -> None:
    _validate_fingerprint(value, "fingerprint", "metric-definition-v1")
    if value.role not in {PREREGISTERED_PRIMARY, PREREGISTERED_SECONDARY}:
        raise ResearchGovernanceError("Metric definition is not preregistered")


def validate_benchmark_definition(value: BenchmarkDefinition) -> None:
    _validate_fingerprint(value, "fingerprint", "benchmark-definition-v1")


def validate_criterion_definition(value: CriterionDefinition) -> None:
    _validate_fingerprint(value, "fingerprint", "criterion-definition-v1")
    _choice(value.criterion_kind, {"SUCCESS", "FAILURE"}, "Criterion kind")
    _finite_number(value.threshold, "Criterion threshold")


def validate_parameter_space(value: ParameterSpace) -> None:
    _validate_fingerprint(value, "fingerprint", "parameter-space-v1")
    if not value.allowed_values or len(value.allowed_values) != len(set(value.allowed_values)):
        raise ResearchGovernanceError("Parameter space must contain unique allowed values")


def validate_parameter_search_policy(value: ParameterSearchPolicy) -> None:
    _validate_fingerprint(value, "fingerprint", "parameter-search-policy-v1")
    _choice(value.search_method, SEARCH_METHODS, "Parameter-search method")
    _positive_int(value.planned_variant_count, "Planned variant count")
    if len({item.parameter_name for item in value.parameter_space}) != len(
        value.parameter_space
    ):
        raise ResearchGovernanceError("Parameter names must be unique")
    for item in value.parameter_space:
        validate_parameter_space(item)


def validate_holdout_policy(value: HoldoutPolicy) -> None:
    _validate_fingerprint(value, "fingerprint", "holdout-policy-v1")
    if value.initial_state not in {SEALED, NOT_APPLICABLE}:
        raise ResearchGovernanceError("Invalid initial holdout state")
    if value.initial_state == SEALED:
        _sha256(value.holdout_identity, "Holdout identity")
        _parse_timestamp(value.final_access_not_before)
        _text(value.final_access_gate, "Holdout access gate")
    elif any(
        item is not None
        for item in (
            value.holdout_identity,
            value.final_access_not_before,
            value.final_access_gate,
        )
    ):
        raise ResearchGovernanceError("Not-applicable holdout defines an access gate")


def validate_research_experiment(value: ResearchExperiment) -> None:
    _validate_fingerprint(value, "fingerprint", "research-experiment-v1")
    if value.contract_version != CONTRACT_VERSION or value.profile != REGISTRY_PROFILE:
        raise ResearchGovernanceError("Experiment contract identity is unsupported")
    _require_research_authority(value.authority, value.execution_authority)
    if value.status != PREREGISTERED:
        raise ResearchGovernanceError("Research experiment must remain preregistered")
    _choice(value.research_timing, RESEARCH_TIMINGS, "Research timing")
    _choice(value.research_intent, RESEARCH_INTENTS, "Research intent")
    _git_sha(value.code_git_identity, "Experiment Git identity")
    _sha256(value.policy_fingerprint, "Experiment policy fingerprint")
    if _parse_timestamp(value.preregistered_at) < _parse_timestamp(value.created_at):
        raise ResearchGovernanceError("Preregistration precedes creation")
    if not value.input_sample_identities or not value.input_dataset_identities:
        raise ResearchGovernanceError("Experiment requires exact sample and dataset identities")
    if not value.feature_definitions or not value.metric_definitions:
        raise ResearchGovernanceError("Experiment requires features and metrics")
    if not value.success_criteria or not value.failure_criteria:
        raise ResearchGovernanceError("Experiment requires success and failure criteria")
    if not value.data_partitions:
        raise ResearchGovernanceError("Experiment requires explicit data partitions")
    _require_unique(
        ((item.feature_id, item.feature_version) for item in value.feature_definitions),
        "Feature definition",
    )
    _require_unique(
        ((item.metric_id, item.metric_version) for item in value.metric_definitions),
        "Metric definition",
    )
    _require_unique((item.role for item in value.data_partitions), "Partition role")
    for item in value.input_sample_identities:
        validate_sample_identity(item)
    for item in value.input_dataset_identities:
        validate_dataset_identity(item)
    for item in value.feature_definitions:
        validate_feature_definition(item)
    for item in value.metric_definitions:
        validate_metric_definition(item)
    validate_benchmark_definition(value.benchmark_definition)
    validate_holdout_policy(value.holdout_policy)
    validate_parameter_search_policy(value.parameter_search_policy)
    sample_pairs = {
        (item.sample_identity, item.fingerprint) for item in value.input_sample_identities
    }
    dataset_pairs = {
        (item.dataset_identity, item.fingerprint)
        for item in value.input_dataset_identities
    }
    for partition in value.data_partitions:
        validate_data_partition(partition)
        if (partition.sample_identity, partition.sample_fingerprint) not in sample_pairs:
            raise ResearchGovernanceError("Partition sample identity drift")
        if (partition.dataset_identity, partition.dataset_fingerprint) not in dataset_pairs:
            raise ResearchGovernanceError("Partition dataset identity drift")
    holdout_partitions = [item for item in value.data_partitions if item.role == HOLDOUT]
    if value.holdout_policy.initial_state == SEALED and len(holdout_partitions) != 1:
        raise ResearchGovernanceError("A sealed holdout requires one HOLDOUT partition")
    if value.holdout_policy.initial_state == NOT_APPLICABLE and holdout_partitions:
        raise ResearchGovernanceError("Not-applicable holdout cannot have HOLDOUT partition")
    if value.require_independent_partitions:
        ordered = sorted(
            value.data_partitions, key=lambda item: _parse_timestamp(item.starts_at)
        )
        for previous, current in zip(ordered, ordered[1:]):
            if _parse_timestamp(current.starts_at) < _parse_timestamp(previous.ends_at):
                raise ResearchGovernanceError("Independent data partitions overlap")
    metric_ids = {item.metric_id for item in value.metric_definitions}
    for criterion in tuple(value.success_criteria) + tuple(value.failure_criteria):
        validate_criterion_definition(criterion)
        if criterion.metric_id not in metric_ids:
            raise ResearchGovernanceError("Criterion references an undeclared metric")
    if any(item.criterion_kind != "SUCCESS" for item in value.success_criteria):
        raise ResearchGovernanceError("Success criteria contain a non-success criterion")
    if any(item.criterion_kind != "FAILURE" for item in value.failure_criteria):
        raise ResearchGovernanceError("Failure criteria contain a non-failure criterion")
    feature_set = _feature_set_fingerprint(value.feature_definitions)
    if feature_set not in value.parameter_search_policy.allowed_feature_set_fingerprints:
        raise ResearchGovernanceError("Experiment feature set is outside its search policy")


def validate_experiment_amendment(value: ExperimentAmendment) -> None:
    _validate_fingerprint(value, "fingerprint", "experiment-amendment-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported amendment contract")
    _choice(
        value.outcome_knowledge_status,
        OUTCOME_KNOWLEDGE_STATES,
        "Outcome knowledge status",
    )
    if value.prior_fingerprint != value.experiment_fingerprint:
        raise ResearchGovernanceError("Amendment prior fingerprint mismatch")


def validate_experiment_variant(value: ExperimentVariant) -> None:
    _validate_fingerprint(value, "fingerprint", "experiment-variant-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported variant contract")
    _choice(value.status, VARIANT_STATUSES, "Variant status")
    _choice(
        value.search_space_status,
        {WITHIN_PREREGISTERED_SPACE, UNPLANNED_SEARCH_EXPANSION},
        "Variant search-space status",
    )
    if value.search_space_status == UNPLANNED_SEARCH_EXPANSION and value.status != INVALID:
        raise ResearchGovernanceError("Unplanned search expansion is not invalid")
    if value.evaluated_at and _parse_timestamp(value.evaluated_at) < _parse_timestamp(
        value.created_at
    ):
        raise ResearchGovernanceError("Variant chronology is invalid")


def validate_holdout_access_receipt(value: HoldoutAccessReceipt) -> None:
    _validate_fingerprint(value, "fingerprint", "holdout-access-receipt-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported holdout receipt contract")
    _choice(
        value.authorization_state,
        HOLDOUT_AUTHORIZATION_STATES,
        "Holdout authorization state",
    )
    _choice(value.resulting_holdout_state, HOLDOUT_STATES, "Holdout resulting state")
    _nonnegative_int(value.prior_access_count, "Prior holdout access count")


def validate_metric_observation(value: MetricObservation) -> None:
    _validate_fingerprint(value, "fingerprint", "metric-observation-v1")
    _choice(value.metric_role, METRIC_ROLES, "Metric observation role")
    _finite_number(value.value, "Metric value", allow_none=True)


def validate_experiment_result(value: ExperimentResult) -> None:
    _validate_fingerprint(value, "result_fingerprint", "experiment-result-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported result contract")
    _require_research_authority(value.authority, value.execution_authority)
    _choice(value.conclusion, RESULT_CONCLUSIONS, "Result conclusion")
    _choice(value.research_timing, RESEARCH_TIMINGS, "Result timing")
    _choice(value.research_intent, RESEARCH_INTENTS, "Result intent")
    _choice(value.holdout_state, HOLDOUT_STATES, "Result holdout state")
    _nonnegative_int(value.actual_sample, "Actual sample")
    for item in tuple(value.metrics) + tuple(value.benchmark_metrics):
        validate_metric_observation(item)


def validate_experiment_invalidation(value: ExperimentInvalidation) -> None:
    _validate_fingerprint(value, "fingerprint", "experiment-invalidation-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported invalidation contract")


def validate_model_health_metric_definition(
    value: ModelHealthMetricDefinition,
) -> None:
    _validate_fingerprint(value, "fingerprint", "model-health-metric-v1")
    _choice(value.failure_comparator, {"LT", "LTE", "GT", "GTE", "EQ"}, "Comparator")


def validate_model_health_policy(value: ModelHealthPolicy) -> None:
    _validate_fingerprint(value, "fingerprint", "model-health-policy-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported health-policy contract")
    _require_research_authority(value.authority, value.execution_authority)
    _positive_int(value.minimum_sample, "Health minimum sample")
    if not value.health_metrics:
        raise ResearchGovernanceError("Health policy needs a versioned metric")
    for item in value.health_metrics:
        validate_model_health_metric_definition(item)


def validate_model_health_record(value: ModelHealthRecord) -> None:
    _validate_fingerprint(value, "fingerprint", "model-health-record-v1")
    if value.contract_version != CONTRACT_VERSION:
        raise ResearchGovernanceError("Unsupported health-record contract")
    _require_research_authority(value.authority, value.execution_authority)
    _choice(value.health_state, MODEL_HEALTH_STATES, "Model-health state")
    _choice(value.evidence_kind, HEALTH_EVIDENCE_KINDS, "Health evidence kind")
    if value.health_state == HEALTHY and value.evidence_kind in {
        UNIT_TEST_ONLY,
        SYNTHETIC_EVIDENCE,
    }:
        raise ResearchGovernanceError("Synthetic evidence cannot prove health")
    for item in value.health_metrics:
        validate_metric_observation(item)


def _derive_holdout_state(
    experiment: ResearchExperiment,
    receipts: Sequence[HoldoutAccessReceipt],
) -> str:
    if experiment.holdout_policy.initial_state == NOT_APPLICABLE:
        if receipts:
            raise ResearchGovernanceError("Holdout receipts exist for not-applicable holdout")
        return NOT_APPLICABLE
    state = SEALED
    prior_fingerprint: str | None = None
    for index, receipt in enumerate(receipts):
        if receipt.prior_access_count != index:
            raise ResearchGovernanceError("Holdout receipt count is not contiguous")
        if receipt.prior_receipt_fingerprint != prior_fingerprint:
            raise ResearchGovernanceError("Holdout receipt chain is broken")
        if receipt.holdout_identity != experiment.holdout_policy.holdout_identity:
            raise ResearchGovernanceError("Holdout receipt identity drift")
        if state == CONTAMINATED_BY_EARLY_ACCESS and (
            receipt.resulting_holdout_state != CONTAMINATED_BY_EARLY_ACCESS
        ):
            raise ResearchGovernanceError("A contaminated holdout cannot be resealed")
        state = receipt.resulting_holdout_state
        prior_fingerprint = receipt.fingerprint
    return state


def summarize_registry(snapshot: RegistrySnapshot) -> RegistrySummary:
    audit_registry_snapshot(snapshot)
    variant_counts = _counts(item.status for item in snapshot.variants)
    conclusion_counts = _counts(item.conclusion for item in snapshot.results)
    health_counts = _counts(item.health_state for item in snapshot.model_health_records)
    holdout_states = [
        _derive_holdout_state(
            experiment,
            tuple(
                sorted(
                    (
                        item
                        for item in snapshot.holdout_access
                        if item.experiment_fingerprint == experiment.fingerprint
                    ),
                    key=lambda item: item.prior_access_count,
                )
            ),
        )
        for experiment in snapshot.experiments
    ]
    return RegistrySummary(
        experiments_registered=len(snapshot.experiments),
        prospective=sum(item.research_timing == PROSPECTIVE for item in snapshot.experiments),
        retrospective=sum(
            item.research_timing in {RETROSPECTIVE_EXPLORATORY, RETROSPECTIVE_CONFIRMATORY}
            for item in snapshot.experiments
        ),
        exploratory=sum(item.research_intent == EXPLORATORY for item in snapshot.experiments),
        confirmatory=sum(item.research_intent == CONFIRMATORY for item in snapshot.experiments),
        variants_attempted=len(snapshot.variants),
        variants_valid=sum(item.status not in {INVALID, FAILED} for item in snapshot.variants),
        variants_invalid=sum(item.status in {INVALID, FAILED} for item in snapshot.variants),
        variant_status_counts=tuple(sorted(variant_counts.items())),
        result_conclusion_counts=tuple(sorted(conclusion_counts.items())),
        sealed_holdouts=holdout_states.count(SEALED),
        opened_holdouts=holdout_states.count(OPENED_FOR_FINAL_EVALUATION),
        contaminated_holdouts=holdout_states.count(CONTAMINATED_BY_EARLY_ACCESS),
        not_applicable_holdouts=holdout_states.count(NOT_APPLICABLE),
        model_health_state_counts=tuple(sorted(health_counts.items())),
        planned_variant_count=sum(
            item.parameter_search_policy.planned_variant_count
            for item in snapshot.experiments
        ),
        planned_metric_count=sum(
            item.parameter_search_policy.planned_metric_count
            for item in snapshot.experiments
        ),
        planned_feature_set_count=sum(
            item.parameter_search_policy.planned_feature_set_count
            for item in snapshot.experiments
        ),
        actual_metric_count=sum(item.actual_metric_count for item in snapshot.results),
        actual_feature_set_count=sum(
            item.actual_feature_set_count for item in snapshot.results
        ),
        selection_occurred_count=sum(item.selection_occurred for item in snapshot.results),
    )


def audit_registry_snapshot(snapshot: RegistrySnapshot) -> None:
    _require_unique(
        ((item.experiment_id, item.experiment_version) for item in snapshot.experiments),
        "Experiment identity",
    )
    _require_unique((item.amendment_id for item in snapshot.amendments), "Amendment ID")
    _require_unique(
        ((item.experiment_id, item.variant_id) for item in snapshot.variants),
        "Variant identity",
    )
    _require_unique((item.result_id for item in snapshot.results), "Result ID")
    _require_unique((item.receipt_id for item in snapshot.holdout_access), "Receipt ID")
    _require_unique(
        (item.invalidation_id for item in snapshot.invalidations), "Invalidation ID"
    )
    _require_unique(
        ((item.policy_id, item.policy_version) for item in snapshot.model_health_policies),
        "Health policy identity",
    )
    _require_unique((item.record_id for item in snapshot.model_health_records), "Health record ID")
    experiments = {item.fingerprint: item for item in snapshot.experiments}
    variants = {item.fingerprint: item for item in snapshot.variants}
    results = {item.result_fingerprint: item for item in snapshot.results}
    results_by_id = {item.result_id: item for item in snapshot.results}
    receipts = {item.fingerprint: item for item in snapshot.holdout_access}
    policies = {item.fingerprint: item for item in snapshot.model_health_policies}
    for experiment in snapshot.experiments:
        validate_research_experiment(experiment)
    for amendment in snapshot.amendments:
        validate_experiment_amendment(amendment)
        _require_experiment_reference(amendment, experiments)
    for invalidation in snapshot.invalidations:
        validate_experiment_invalidation(invalidation)
        _require_experiment_reference(invalidation, experiments)
    for variant in snapshot.variants:
        validate_experiment_variant(variant)
        experiment = _require_experiment_reference(variant, experiments)
        if variant.data_fingerprint not in {
            fingerprint
            for item in experiment.input_dataset_identities
            for fingerprint in (item.fingerprint, item.dataset_fingerprint)
        }:
            raise ResearchGovernanceError("Variant data identity drift")
        if variant.code_identity != experiment.code_git_identity:
            raise ResearchGovernanceError("Variant code identity drift")
        if variant.status in {EVALUATED, NULL_RESULT}:
            result = results_by_id.get(variant.result_identity or "")
            if result is None or result.variant_fingerprint != variant.fingerprint:
                raise ResearchGovernanceError("Evaluated variant result is missing")
    for result in snapshot.results:
        validate_experiment_result(result)
        experiment = experiments.get(result.experiment_fingerprint)
        variant = variants.get(result.variant_fingerprint)
        if experiment is None or result.experiment_id != experiment.experiment_id:
            raise ResearchGovernanceError("Result is attached to the wrong experiment")
        if variant is None or result.variant_id != variant.variant_id:
            raise ResearchGovernanceError("Result is attached to the wrong variant")
        if variant.experiment_fingerprint != experiment.fingerprint:
            raise ResearchGovernanceError("Result variant/experiment relationship is wrong")
        if variant.result_identity != result.result_id:
            raise ResearchGovernanceError("Variant result identity drift")
        if result.research_timing != experiment.research_timing:
            raise ResearchGovernanceError("Retrospective/prospective identity drift")
        if result.research_intent != experiment.research_intent:
            raise ResearchGovernanceError("Exploratory/confirmatory identity drift")
        eligible_variants = [
            item
            for item in snapshot.variants
            if item.experiment_fingerprint == experiment.fingerprint
            and _parse_timestamp(item.created_at) <= _parse_timestamp(result.evaluated_at)
        ]
        if result.actual_variant_count != len(eligible_variants):
            raise ResearchGovernanceError(
                "Result attempted-variant count does not match the preserved ledger"
            )
        feature_sets = {item.feature_set_fingerprint for item in eligible_variants}
        if result.actual_feature_set_count != len(feature_sets):
            raise ResearchGovernanceError(
                "Result feature-set count does not match the preserved ledger"
            )
        if result.actual_metric_count < len(
            {
                (item.metric_id, item.metric_version)
                for item in tuple(result.metrics) + tuple(result.benchmark_metrics)
            }
        ):
            raise ResearchGovernanceError("Result metric-inspection count is understated")
        result_receipts = []
        for fingerprint in result.holdout_access_receipt_fingerprints:
            receipt = receipts.get(fingerprint)
            if receipt is None:
                raise ResearchGovernanceError("Result holdout receipt was deleted")
            result_receipts.append(receipt)
        expected_state = _derive_holdout_state(
            experiment,
            tuple(sorted(result_receipts, key=lambda item: item.prior_access_count)),
        )
        if result.holdout_state != expected_state:
            raise ResearchGovernanceError("Result holdout claim is false")
    for receipt in snapshot.holdout_access:
        validate_holdout_access_receipt(receipt)
        _require_experiment_reference(receipt, experiments)
    for experiment in snapshot.experiments:
        experiment_receipts = tuple(
            sorted(
                (
                    item
                    for item in snapshot.holdout_access
                    if item.experiment_fingerprint == experiment.fingerprint
                ),
                key=lambda item: item.prior_access_count,
            )
        )
        _derive_holdout_state(experiment, experiment_receipts)
    for policy in snapshot.model_health_policies:
        validate_model_health_policy(policy)
    for record in snapshot.model_health_records:
        validate_model_health_record(record)
        policy = policies.get(record.health_policy_fingerprint)
        if policy is None or record.health_policy_id != policy.policy_id:
            raise ResearchGovernanceError("Model-health policy is missing or changed")
        if record.benchmark_fingerprint != policy.benchmark_fingerprint:
            raise ResearchGovernanceError("Model-health benchmark drift")
        allowed = {item.fingerprint for item in policy.health_metrics}
        if any(
            item.metric_definition_fingerprint not in allowed
            for item in record.health_metrics
        ):
            raise ResearchGovernanceError("Model-health metric drift")
        if record.health_state == HEALTHY and record.sample_size < policy.minimum_sample:
            raise ResearchGovernanceError("Model health is unsupported by sample size")


_RECORD_LAYOUT: dict[type[Any], tuple[str, str, str]] = {
    ResearchExperiment: ("experiments", "experiment_id", "fingerprint"),
    ExperimentAmendment: ("amendments", "amendment_id", "fingerprint"),
    ExperimentVariant: ("variants", "variant_id", "fingerprint"),
    ExperimentResult: ("results", "result_id", "result_fingerprint"),
    HoldoutAccessReceipt: ("holdout-access", "receipt_id", "fingerprint"),
    ExperimentInvalidation: ("invalidations", "invalidation_id", "fingerprint"),
    ModelHealthPolicy: ("model-health-policies", "policy_id", "fingerprint"),
    ModelHealthRecord: ("model-health", "record_id", "fingerprint"),
}
_RECORD_TYPES: dict[str, type[Any]] = {value.__name__: value for value in _RECORD_LAYOUT}
_RECORD_VALIDATORS = {
    ResearchExperiment: validate_research_experiment,
    ExperimentAmendment: validate_experiment_amendment,
    ExperimentVariant: validate_experiment_variant,
    ExperimentResult: validate_experiment_result,
    HoldoutAccessReceipt: validate_holdout_access_receipt,
    ExperimentInvalidation: validate_experiment_invalidation,
    ModelHealthPolicy: validate_model_health_policy,
    ModelHealthRecord: validate_model_health_record,
}


class ResearchRegistryStore:
    """Caller-rooted, deterministic, write-once registry persistence."""

    def __init__(self, root: str | Path) -> None:
        raw_root = Path(root)
        if not raw_root.is_absolute():
            raise ResearchGovernanceError("Registry root must be an absolute caller path")
        self.root = raw_root.resolve() / REGISTRY_DIRECTORY

    def write(self, record: Any) -> Path:
        record_type = type(record)
        if record_type not in _RECORD_LAYOUT:
            raise ResearchGovernanceError("Record type is not persistable")
        _RECORD_VALIDATORS[record_type](record)
        directory_name, identity_field, _ = _RECORD_LAYOUT[record_type]
        identity = _filename_token(str(getattr(record, identity_field)))
        if isinstance(record, (ResearchExperiment, ExperimentVariant)):
            identity = (
                f"{_filename_token(record.experiment_id)}--{identity}"
                if isinstance(record, ExperimentVariant)
                else f"{identity}--{_filename_token(record.experiment_version)}"
            )
        target_dir = self.root / directory_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{identity}.json"
        envelope = {"recordType": record_type.__name__, "record": _plain(record)}
        encoded = _canonical_json(envelope) + b"\n"
        if target.exists():
            existing = target.read_bytes()
            if existing == encoded:
                self._load_file(target)
                return target
            raise ResearchGovernanceError(f"Conflicting write-once record: {target.name}")
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != encoded:
                    raise ResearchGovernanceError(
                        f"Conflicting concurrent record: {target.name}"
                    )
            finally:
                temporary.unlink(missing_ok=True)
            _fsync_directory(target_dir)
            self._load_file(target)
            return target
        except Exception:
            if temporary.exists() and target.exists() and target.read_bytes() == encoded:
                temporary.unlink(missing_ok=True)
            raise

    def load_snapshot(self) -> RegistrySnapshot:
        if not self.root.exists():
            return RegistrySnapshot()
        partials = tuple(self.root.rglob("*.tmp"))
        if partials:
            raise ResearchGovernanceError(
                f"Partial registry write is present: {partials[0].name}"
            )
        records: dict[type[Any], list[Any]] = {record_type: [] for record_type in _RECORD_LAYOUT}
        expected_directories = {value[0] for value in _RECORD_LAYOUT.values()}
        for path in sorted(self.root.rglob("*.json")):
            relative = path.relative_to(self.root)
            if len(relative.parts) != 2 or relative.parts[0] not in expected_directories:
                raise ResearchGovernanceError(f"Unexpected registry path: {relative}")
            record = self._load_file(path)
            expected_directory = _RECORD_LAYOUT[type(record)][0]
            if relative.parts[0] != expected_directory:
                raise ResearchGovernanceError("Registry record is in the wrong collection")
            records[type(record)].append(record)
        snapshot = RegistrySnapshot(
            experiments=tuple(records[ResearchExperiment]),
            amendments=tuple(records[ExperimentAmendment]),
            variants=tuple(records[ExperimentVariant]),
            results=tuple(records[ExperimentResult]),
            holdout_access=tuple(records[HoldoutAccessReceipt]),
            invalidations=tuple(records[ExperimentInvalidation]),
            model_health_policies=tuple(records[ModelHealthPolicy]),
            model_health_records=tuple(records[ModelHealthRecord]),
        )
        audit_registry_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _load_file(path: Path) -> Any:
        try:
            envelope = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchGovernanceError(f"Malformed registry record: {path.name}") from exc
        if not isinstance(envelope, dict) or set(envelope) != {"recordType", "record"}:
            raise ResearchGovernanceError(f"Malformed registry envelope: {path.name}")
        record_type = _RECORD_TYPES.get(envelope["recordType"])
        if record_type is None or not isinstance(envelope["record"], dict):
            raise ResearchGovernanceError(f"Unsupported registry record: {path.name}")
        try:
            record = _dataclass_from_dict(record_type, envelope["record"])
            _RECORD_VALIDATORS[record_type](record)
        except (KeyError, TypeError, ResearchGovernanceError) as exc:
            raise ResearchGovernanceError(f"Invalid registry record: {path.name}: {exc}") from exc
        expected = _canonical_json({"recordType": record_type.__name__, "record": _plain(record)}) + b"\n"
        if path.read_bytes() != expected:
            raise ResearchGovernanceError(f"Noncanonical or tampered record: {path.name}")
        return record


def specialist_registration_fixtures() -> tuple[SpecialistFixtureMetadata, ...]:
    raw = (
        (
            "REGIME_EXHAUSTION",
            "regime-exhaustion-research-v1",
            "regime-exhaustion-research-policy-v1",
            "55d5e05f91553381ba162c70b09c5f9987262edfbe2a9ec687214cc29f9d1057",
            "codex/ARGUS-REGIME-002-exhaustion-market-stress",
            "99a25f84219377e9988e8284aa15a944e3936784",
            "Does LATE_TREND classification add useful information beyond Momentum?",
        ),
        (
            "EXECUTION_QUALITY",
            "execution-quality-research-v1",
            "execution-quality-research-policy-v1",
            "5b831e70e92827104df23e116a4d679835f7e693292750f9b85f0d34e080f1df",
            "codex/ARGUS-EXEC-QUALITY-001-liquidity-execution-research",
            "1b105e71d99d45a8ed8099ae4001bd9c6ba2242f",
            "Does spread relative to stop distance predict worse realized execution?",
        ),
        (
            "EVENT_SHOCK",
            "event-shock-reaction-research-v1",
            "event-shock-policy-v1",
            "4c9f9b45eef58b6b6bb8235aee21711bbdea2048566941a9ff07c3f58458dc49",
            "codex/ARGUS-EVENT-SHOCK-001-event-reaction-research",
            "fe8ca09556fe8ea3dd81949e59ac26d8e3d86da4",
            "Does news/price disagreement predict worse continuation outcomes?",
        ),
    )
    fixtures = []
    for specialist_id, version, policy_id, policy_fingerprint, branch, commit, question in raw:
        payload = {
            "specialist_id": specialist_id,
            "specialist_version": version,
            "specialist_policy_id": policy_id,
            "specialist_policy_fingerprint": policy_fingerprint,
            "source_branch": branch,
            "source_commit": commit,
            "experiment_id": f"research-gov-fixture-{specialist_id.lower().replace('_', '-')}-v1",
            "research_question": question,
            "status": "STATIC_UNACTIVATED_FIXTURE",
        }
        fixtures.append(
            SpecialistFixtureMetadata(
                **payload, fingerprint=_fingerprint("specialist-fixture-metadata-v1", payload)
            )
        )
    return tuple(fixtures)


def stat_data_compatibility() -> StatDataCompatibility:
    payload = {
        "contract_version": 1,
        "source_branch": "codex/ARGUS-STAT-DATA-001-prospective-opportunity-denominator",
        "source_commit": "cd95490661b54c73af162c8b9f651039006ad0c6",
        "sample_identity": "opportunity-denominator-research-v1",
        "policy_id": "opportunity-denominator-policy-v1",
        "policy_fingerprint": "fa0f034b224bea1f053ce85cbfbc37b7961b257c46514070b422476b190fc5e8",
        "sample_status": "INACTIVE_ZERO_OBSERVATIONS",
        "sessions": 0,
        "opportunities": 0,
        "import_mode": "STATIC_IDENTITY_ONLY_NO_RUNTIME_IMPORT",
        "compatible": True,
    }
    return StatDataCompatibility(
        **payload, fingerprint=_fingerprint("stat-data-compatibility-v1", payload)
    )


def research_data_compatibility() -> ResearchDataCompatibility:
    payload = {
        "source_branch": "codex/ARGUS-RESEARCH-DATA-002-security-action-basis",
        "source_commit": "12e6a05d0f1f2e860edb522c7a9247c3a39fbdf6",
        "report_fingerprint": "3c763cff90d9cfe5c1c5b75b55e2abbb5d0e759883519317de1acbd199efad8bc",
        "classification": "IDENTITY_AND_PRICE_BASIS_FOUNDATION_DEFINED_GAPS_REMAIN",
        "data_basis_status": UNRESOLVED,
        "survivorship_status": UNCONTROLLED,
        "security_identity_status": UNRESOLVED,
        "point_in_time_universe_status": INSUFFICIENT,
        "historically_robust": False,
    }
    return ResearchDataCompatibility(
        **payload, fingerprint=_fingerprint("research-data-compatibility-v1", payload)
    )


def build_static_specialist_experiments() -> tuple[ResearchExperiment, ...]:
    """Build unactivated in-memory examples bound to current specialist identities."""

    experiments = []
    for index, fixture in enumerate(specialist_registration_fixtures()):
        sample = build_sample_identity(
            sample_identity=f"{fixture.specialist_id.lower()}-static-fixture-sample-v1",
            policy_fingerprint=fixture.specialist_policy_fingerprint,
            sample_status="STATIC_UNACTIVATED_FIXTURE",
        )
        dataset_fingerprint = _digest_text(
            f"{fixture.specialist_id}:research-data-002-limited-static-fixture"
        )
        dataset = build_dataset_identity(
            dataset_identity=f"{fixture.specialist_id.lower()}-static-fixture-dataset-v1",
            dataset_fingerprint=dataset_fingerprint,
            source_fingerprints=(_digest_text(f"{fixture.specialist_id}:source"),),
            data_basis_status=INSUFFICIENT,
            survivorship_status=UNCONTROLLED,
            security_identity_status=UNRESOLVED,
            point_in_time_universe_status=INSUFFICIENT,
            historically_robust=False,
        )
        feature = build_feature_definition(
            feature_id=f"{fixture.specialist_id.lower()}-opinion",
            feature_version=fixture.specialist_version,
            semantic_description=(
                "Static specialist opinion identity for registry contract proof; no outcome "
                "is evaluated and no runtime specialist is imported."
            ),
            inputs=("persisted-specialist-opinion",),
            transformation="identity-only static fixture",
            time_horizon="same-session research",
            price_basis_requirement="UNRESOLVED_RESEARCH_DATA_LIMITATION",
            evidence_family=fixture.specialist_id,
        )
        metric = build_metric_definition(
            metric_id="incremental-information-v1",
            metric_version="1",
            semantic_description="Difference from the versioned baseline on a frozen outcome metric.",
            formula="specialist_metric - benchmark_metric",
            direction="HIGHER_IS_BETTER",
            role=PREREGISTERED_PRIMARY,
        )
        benchmark = build_benchmark_definition(
            benchmark_id="current-momentum-baseline",
            benchmark_version="1",
            semantic_description="Current Momentum research baseline frozen before evaluation.",
            source_identity="STATIC_RESEARCH_BASELINE_ONLY",
        )
        success = build_criterion_definition(
            criterion_id="incremental-information-positive",
            criterion_kind="SUCCESS",
            metric_id=metric.metric_id,
            comparator="GT",
            threshold=0.0,
            semantic_description="Preregistered metric exceeds the frozen baseline.",
        )
        failure = build_criterion_definition(
            criterion_id="incremental-information-not-positive",
            criterion_kind="FAILURE",
            metric_id=metric.metric_id,
            comparator="LTE",
            threshold=0.0,
            semantic_description="Preregistered metric does not exceed the frozen baseline.",
        )
        periods = (
            (TRAIN, datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 4, 1, tzinfo=timezone.utc)),
            (VALIDATION, datetime(2024, 4, 1, tzinfo=timezone.utc), datetime(2024, 7, 1, tzinfo=timezone.utc)),
            (TEST, datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 10, 1, tzinfo=timezone.utc)),
            (HOLDOUT, datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc)),
        )
        partitions = tuple(
            build_data_partition(
                role=role,
                starts_at=starts_at,
                ends_at=ends_at,
                sample=sample,
                dataset=dataset,
            )
            for role, starts_at, ends_at in periods
        )
        holdout = build_holdout_policy(
            initial_state=SEALED,
            holdout_identity=_digest_text(f"{fixture.experiment_id}:holdout"),
            final_access_not_before=datetime(2026, 9, 1, tzinfo=timezone.utc),
            final_access_gate="Only an explicitly authorized final evaluation may open holdout.",
        )
        search = build_parameter_search_policy(
            search_method=SINGLE_PREREGISTERED_VARIANT,
            planned_variant_count=1,
            parameter_space=(
                build_parameter_space(
                    parameter_name="specialistVersion",
                    allowed_values=(fixture.specialist_version,),
                ),
            ),
            allowed_feature_set_fingerprints=(_feature_set_fingerprint((feature,)),),
            allowed_model_families=(fixture.specialist_id,),
            planned_metric_count=1,
            planned_feature_set_count=1,
        )
        created = datetime(2026, 8, 14, 18, index, tzinfo=timezone.utc)
        experiments.append(
            build_research_experiment(
                experiment_id=fixture.experiment_id,
                experiment_version="1",
                title=f"Static {fixture.specialist_id} registry fixture",
                research_question=fixture.research_question,
                hypothesis="The versioned specialist adds information beyond its frozen baseline.",
                created_at=created,
                preregistered_at=created,
                research_domain=fixture.specialist_id,
                research_timing=RETROSPECTIVE_CONFIRMATORY,
                research_intent=CONFIRMATORY,
                code_git_identity=fixture.source_commit,
                policy_fingerprint=fixture.specialist_policy_fingerprint,
                input_sample_identities=(sample,),
                input_dataset_identities=(dataset,),
                feature_definitions=(feature,),
                metric_definitions=(metric,),
                benchmark_definition=benchmark,
                success_criteria=(success,),
                failure_criteria=(failure,),
                data_partitions=partitions,
                holdout_policy=holdout,
                parameter_search_policy=search,
                planned_minimum_sample=100,
            )
        )
    return tuple(experiments)


def _require_research_authority(authority: str, execution_authority: str) -> None:
    if authority != RESEARCH_ONLY or execution_authority != EXECUTION_AUTHORITY_NONE:
        raise ResearchGovernanceError("Research governance cannot acquire trading authority")


def _require_experiment_reference(
    value: Any, experiments: Mapping[str, ResearchExperiment]
) -> ResearchExperiment:
    experiment = experiments.get(value.experiment_fingerprint)
    if experiment is None or value.experiment_id != experiment.experiment_id:
        raise ResearchGovernanceError("Record references a missing or wrong experiment")
    return experiment


def _validate_fingerprint(value: Any, field_name: str, namespace: str) -> None:
    if not is_dataclass(value):
        raise ResearchGovernanceError("Registry value is not an immutable contract record")
    payload = {
        field.name: getattr(value, field.name)
        for field in fields(value)
        if field.name != field_name
    }
    expected = _fingerprint(namespace, payload)
    actual = getattr(value, field_name)
    if actual != expected:
        raise ResearchGovernanceError(f"{type(value).__name__} fingerprint mismatch")


def _feature_set_fingerprint(features: Sequence[FeatureDefinition]) -> str:
    return _fingerprint(
        "feature-set-v1",
        tuple(sorted((item.fingerprint for item in features))),
    )


def _fingerprint(namespace: str, value: Any) -> str:
    payload = {"namespace": namespace, "value": _plain(value)}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResearchGovernanceError("Non-finite values are not canonical")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ResearchGovernanceError(f"Unsupported canonical value: {type(value).__name__}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchGovernanceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _dataclass_from_dict(record_type: type[Any], payload: Mapping[str, Any]) -> Any:
    expected_fields = {item.name for item in fields(record_type)}
    if set(payload) != expected_fields:
        missing = sorted(expected_fields - set(payload))
        extra = sorted(set(payload) - expected_fields)
        raise ResearchGovernanceError(
            f"Record fields differ; missing={missing}, extra={extra}"
        )
    hints = get_type_hints(record_type)
    return record_type(
        **{
            item.name: _coerce_value(hints[item.name], payload[item.name])
            for item in fields(record_type)
        }
    )


def _coerce_value(annotation: Any, value: Any) -> Any:
    if is_dataclass(annotation):
        if not isinstance(value, Mapping):
            raise ResearchGovernanceError("Nested contract record is malformed")
        return _dataclass_from_dict(annotation, value)
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is tuple:
        if not isinstance(value, list):
            raise ResearchGovernanceError("Tuple contract field is malformed")
        item_annotation = arguments[0] if arguments else Any
        return tuple(_coerce_value(item_annotation, item) for item in value)
    if origin in {types.UnionType} or (
        origin is not None and str(origin) == "typing.Union"
    ):
        if value is None and type(None) in arguments:
            return None
        failures = []
        for option in arguments:
            if option is type(None):
                continue
            try:
                return _coerce_value(option, value)
            except (ResearchGovernanceError, TypeError, ValueError) as exc:
                failures.append(exc)
        raise ResearchGovernanceError("Union contract field is malformed") from (
            failures[-1] if failures else None
        )
    if annotation is Any:
        return value
    if annotation is bool:
        if type(value) is not bool:
            raise ResearchGovernanceError("Boolean contract field is malformed")
        return value
    if annotation is int:
        if type(value) is not int:
            raise ResearchGovernanceError("Integer contract field is malformed")
        return value
    if annotation is float:
        return _finite_number(value, "Numeric contract field")
    if annotation is str:
        if not isinstance(value, str):
            raise ResearchGovernanceError("String contract field is malformed")
        return value
    return value


def _token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value.strip()):
        raise ResearchGovernanceError(f"{label} is missing or malformed")
    return value.strip()


def _tokens(values: Sequence[str], label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    result = tuple(_token(value, label) for value in values)
    if not result and not allow_empty:
        raise ResearchGovernanceError(f"{label} is required")
    if len(result) != len(set(result)):
        raise ResearchGovernanceError(f"{label} contains duplicates")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchGovernanceError(f"{label} is required")
    return value.strip()


def _texts(values: Sequence[str], label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    result = tuple(_text(value, label) for value in values)
    if not result and not allow_empty:
        raise ResearchGovernanceError(f"{label} is required")
    return result


def _scalar_text(value: Any, label: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ResearchGovernanceError(f"{label} must be finite")
        return format(value, ".15g")
    return _text(value, label)


def _choice(value: Any, allowed: Sequence[str] | set[str] | frozenset[str], label: str) -> str:
    if value not in allowed:
        raise ResearchGovernanceError(f"{label} is unsupported: {value!r}")
    return str(value)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ResearchGovernanceError(f"{label} must be SHA-256")
    return value.lower()


def _sha256_values(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(sorted(_sha256(value, label) for value in values))
    if not result or len(result) != len(set(result)):
        raise ResearchGovernanceError(f"{label} must be nonempty and unique")
    return result


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise ResearchGovernanceError(f"{label} must be a full Git SHA")
    return value.lower()


def _finite_number(value: Any, label: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchGovernanceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ResearchGovernanceError(f"{label} must be finite")
    return result


def _finite(value: Any, label: str) -> float:
    result = _finite_number(value, label)
    assert result is not None
    return result


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ResearchGovernanceError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ResearchGovernanceError(f"{label} must be a nonnegative integer")
    return value


def _aware(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchGovernanceError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ResearchGovernanceError("Timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchGovernanceError("Timestamp is malformed") from exc
    return _aware(parsed, "Timestamp")


def _timestamp(value: Any, label: str) -> str:
    if isinstance(value, datetime):
        return _iso(_aware(value, label))
    try:
        return _iso(_parse_timestamp(value))
    except ResearchGovernanceError as exc:
        raise ResearchGovernanceError(f"{label} is malformed") from exc


def _require_unique(values: Sequence[Any] | Any, label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ResearchGovernanceError(f"Duplicate {label}")


def _counts(values: Sequence[str] | Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _filename_token(value: str) -> str:
    return _token(value, "Record filename identity").replace(":", "_")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
