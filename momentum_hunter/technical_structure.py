"""Deterministic, offline technical-structure research specialist.

This module evolves the Technical Breakout Research Engine v1 primitives into
prospective structure instances.  It accepts caller-supplied evidence only and
has no provider, account, broker, order, persistence, scheduler, service,
Engine Host, WPF, scoring, selection, or execution capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BEARISH,
    BULLISH,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    NEUTRAL,
    NO_DIRECTION,
    NO_OPINION,
    RESEARCH_ONLY,
    SpecialistOpinion,
    build_evidence_reference,
    build_specialist_opinion,
    validate_opinion_target_identity,
)
from momentum_hunter.technical_breakouts import (
    TechnicalPriceBar,
    cumulative_vwap_values,
    true_range,
)


SCHEMA_VERSION = 2
SPECIALIST_ID = "TECHNICAL_STRUCTURE"
SPECIALIST_VERSION = "technical-structure-research-v2"
RESEARCH_IDENTITY = "technical-structure-research-v2"
STRUCTURE_VERSION = "technical-structure-geometry-v2"

STRUCTURE_SUPPORTS = "STRUCTURE_SUPPORTS"
STRUCTURE_NEUTRAL = "STRUCTURE_NEUTRAL"
STRUCTURE_CONTRADICTS = "STRUCTURE_CONTRADICTS"
STRUCTURE_EXHAUSTED = "STRUCTURE_EXHAUSTED"

COMPRESSION_EXPANSION = "COMPRESSION_EXPANSION"
BREAKOUT_RETEST = "BREAKOUT_RETEST"
FAILED_BREAKOUT = "FAILED_BREAKOUT"
VWAP_RECLAIM = "VWAP_RECLAIM"
VWAP_LOSS = "VWAP_LOSS"
HIGHER_LOW_CONTINUATION = "HIGHER_LOW_CONTINUATION"
LOWER_HIGH_BREAKDOWN = "LOWER_HIGH_BREAKDOWN"
DOUBLE_TOP = "DOUBLE_TOP"
DOUBLE_BOTTOM = "DOUBLE_BOTTOM"
SUPPORT_RESISTANCE = "SUPPORT_RESISTANCE"
HEAD_AND_SHOULDERS = "HEAD_AND_SHOULDERS"
INVERSE_HEAD_AND_SHOULDERS = "INVERSE_HEAD_AND_SHOULDERS"
TECHNICAL_EXHAUSTION = "TECHNICAL_EXHAUSTION"

CONFIRMED_STRUCTURE = "CONFIRMED_STRUCTURE"
POTENTIAL_STRUCTURE = "POTENTIAL_STRUCTURE"
AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
ACTIVE = "ACTIVE"
INVALIDATED = "INVALIDATED"
NOT_APPLICABLE = "NOT_APPLICABLE"

REGULAR = "REGULAR"
PREMARKET = "PREMARKET"
AFTER_HOURS = "AFTER_HOURS"
SESSIONS = frozenset({REGULAR, PREMARKET, AFTER_HOURS})

SAME_SESSION_RAW_PROVIDER = "SAME_SESSION_RAW_PROVIDER"
SPLIT_ADJUSTED_ANALYSIS = "SPLIT_ADJUSTED_ANALYSIS"
TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"
UNKNOWN_PRICE_BASIS = "UNKNOWN"
PRICE_BASES = frozenset(
    {
        SAME_SESSION_RAW_PROVIDER,
        SPLIT_ADJUSTED_ANALYSIS,
        TOTAL_RETURN_ADJUSTED,
        UNKNOWN_PRICE_BASIS,
    }
)
SESSION_BOUND = "SESSION_BOUND"
DURABLE = "DURABLE"
UNKNOWN_IDENTITY = "UNKNOWN"
SECURITY_IDENTITY_STATES = frozenset({SESSION_BOUND, DURABLE, UNKNOWN_IDENTITY})

PIVOT_HIGH = "PIVOT_HIGH"
PIVOT_LOW = "PIVOT_LOW"
SUPPORT = "SUPPORT"
RESISTANCE = "RESISTANCE"
CALLER_FROZEN_LEVEL = "CALLER_FROZEN_LEVEL"
PIVOT_CLUSTER = "PIVOT_CLUSTER"
BAR_DERIVED_VWAP = "BAR_DERIVED_VWAP"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}")


class TechnicalStructureError(ValueError):
    """Raised when technical evidence is malformed, contradictory, or unsafe."""


@dataclass(frozen=True)
class TechnicalStructurePolicy:
    policy_version: str = SPECIALIST_VERSION
    pivot_left_bars: int = 2
    pivot_right_bars: int = 2
    atr_window: int = 14
    minimum_bars: int = 15
    expected_interval_seconds: int = 60
    max_evidence_age_seconds: int = 300
    level_min_touches: int = 2
    level_tolerance_atr: float = 0.20
    breakout_buffer_atr: float = 0.05
    retest_tolerance_atr: float = 0.25
    breakout_failure_horizon_bars: int = 5
    compression_window: int = 6
    compression_ratio_max: float = 0.68
    expansion_range_multiple: float = 1.50
    minimum_retracement: float = 0.20
    maximum_retracement: float = 0.80
    double_extreme_tolerance_atr: float = 0.30
    double_valley_depth_atr: float = 0.50
    shoulder_tolerance_atr: float = 0.40
    head_prominence_atr: float = 0.50
    neckline_tolerance_atr: float = 0.30
    vwap_tolerance_atr: float = 0.05
    exhaustion_extension_atr: float = 2.50
    exhaustion_volume_multiple: float = 2.00
    full_evaluation_sessions: tuple[str, ...] = (REGULAR,)
    premarket_full_path_observed: bool = False


@dataclass(frozen=True)
class TechnicalStructureBar:
    bar_id: str
    symbol: str
    timestamp: str
    completed_at: str | None
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str
    session: str
    price_basis: str
    evidence_fingerprint: str
    completed: bool = True


@dataclass(frozen=True)
class FrozenTechnicalLevel:
    level_id: str
    level_type: str
    price: float
    known_at: str
    origin: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class TechnicalPivot:
    pivot_id: str
    pivot_type: str
    timestamp: str
    known_at: str
    price: float
    bar_id: str
    confirmation_horizon_bars: int
    evidence_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class TechnicalReferenceLevel:
    level_id: str
    level_type: str
    price: float
    origin: str
    first_known_at: str
    known_at: str
    touch_count: int
    tolerance_basis: str
    tolerance_value: float
    invalidation_state: str
    evidence_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class GeometryMeasurement:
    name: str
    absolute: float | None
    percent: float | None
    atr_units: float | None
    recent_range_units: float | None


@dataclass(frozen=True)
class VolatilityContext:
    atr: float
    atr_window: int
    recent_range: float
    as_of: str


@dataclass(frozen=True)
class VolumeContext:
    current_volume: float | None
    average_volume: float | None
    relative_volume: float | None
    source: str


@dataclass(frozen=True)
class TechnicalStructureInstance:
    schema_version: int
    structure_id: str
    structure_version: str
    structure_type: str
    symbol: str
    opportunity_id: str
    setup_id: str | None
    direction: str
    detected_at: str
    known_at: str
    evidence_start: str
    evidence_end: str
    confirmation_state: str
    invalidation_state: str
    reference_levels: tuple[TechnicalReferenceLevel, ...]
    pivots: tuple[TechnicalPivot, ...]
    geometry_measurements: tuple[GeometryMeasurement, ...]
    volatility_normalization: VolatilityContext
    volume_context: VolumeContext
    price_basis: str
    session: str
    policy_fingerprint: str
    evidence_fingerprints: tuple[str, ...]
    reason_codes: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class TechnicalStructureRequest:
    opportunity_id: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    symbol: str
    thesis_direction: str
    as_of: str
    expires_at: str
    session: str
    price_basis: str
    basis_verified: bool
    security_identity_status: str
    corporate_action_safe: bool
    bars: tuple[TechnicalStructureBar, ...]
    frozen_levels: tuple[FrozenTechnicalLevel, ...] = field(default_factory=tuple)
    expected_trade_plan_fingerprint: str | None = None


@dataclass(frozen=True)
class TechnicalStructureEvaluation:
    schema_version: int
    specialist_version: str
    policy_fingerprint: str
    input_evidence_fingerprint: str
    as_of: str
    provisional_bar_count: int
    structures: tuple[TechnicalStructureInstance, ...]
    opinion: SpecialistOpinion
    fingerprint: str


def current_policy() -> TechnicalStructurePolicy:
    policy = TechnicalStructurePolicy()
    validate_policy(policy)
    return policy


def policy_fingerprint(policy: TechnicalStructurePolicy) -> str:
    validate_policy(policy)
    return _fingerprint("technical-structure-policy-v2", asdict(policy))


def build_structure_bar(
    *,
    symbol: str,
    timestamp: datetime | str,
    completed_at: datetime | str | None,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float | None,
    source: str,
    session: str,
    price_basis: str,
    completed: bool = True,
    evidence_fingerprint: str | None = None,
) -> TechnicalStructureBar:
    ts = _timestamp(timestamp, "Bar timestamp")
    completion = (
        _timestamp(completed_at, "Bar completion timestamp")
        if completed_at is not None
        else None
    )
    payload = {
        "symbol": _symbol(symbol),
        "timestamp": ts,
        "completedAt": completion,
        "open": _positive(open_price, "Bar open"),
        "high": _positive(high, "Bar high"),
        "low": _positive(low, "Bar low"),
        "close": _positive(close, "Bar close"),
        "volume": _optional_nonnegative(volume, "Bar volume"),
        "source": _identifier(source, "Bar source"),
        "session": _session(session),
        "priceBasis": _price_basis(price_basis),
        "completed": _boolean(completed, "Bar completion state"),
    }
    if payload["high"] < max(payload["open"], payload["close"], payload["low"]):
        raise TechnicalStructureError("Bar high contradicts OHLC evidence.")
    if payload["low"] > min(payload["open"], payload["close"], payload["high"]):
        raise TechnicalStructureError("Bar low contradicts OHLC evidence.")
    if payload["completed"] and completion is None:
        raise TechnicalStructureError("Completed bar requires completion time.")
    if not payload["completed"] and completion is not None:
        raise TechnicalStructureError("Forming bar cannot claim completion time.")
    if completion is not None and _parse_timestamp(completion) <= _parse_timestamp(ts):
        raise TechnicalStructureError("Bar completion must follow its economic timestamp.")
    calculated_evidence = _fingerprint("technical-structure-bar-evidence-v2", payload)
    supplied = (
        _sha256(evidence_fingerprint, "Bar evidence fingerprint")
        if evidence_fingerprint is not None
        else calculated_evidence
    )
    identity = _fingerprint(
        "technical-structure-bar-identity-v2",
        {"symbol": payload["symbol"], "timestamp": ts, "source": payload["source"]},
    )
    bar = TechnicalStructureBar(
        bar_id=identity,
        symbol=payload["symbol"],
        timestamp=ts,
        completed_at=completion,
        open=payload["open"],
        high=payload["high"],
        low=payload["low"],
        close=payload["close"],
        volume=payload["volume"],
        source=payload["source"],
        session=payload["session"],
        price_basis=payload["priceBasis"],
        evidence_fingerprint=supplied,
        completed=payload["completed"],
    )
    validate_structure_bar(bar)
    return bar


def structure_bar_from_v1(
    bar: TechnicalPriceBar,
    *,
    completed_at: datetime | str,
    session: str,
    price_basis: str,
) -> TechnicalStructureBar:
    """Adapt the existing v1 technical bar without changing its values."""

    if not isinstance(bar, TechnicalPriceBar):
        raise TechnicalStructureError("Technical Breakout v1 bar is malformed.")
    return build_structure_bar(
        symbol=bar.symbol,
        timestamp=bar.timestamp,
        completed_at=completed_at,
        open_price=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        session=session,
        price_basis=price_basis,
    )


def build_frozen_level(
    *,
    level_id: str,
    level_type: str,
    price: float,
    known_at: datetime | str,
    origin: str,
    evidence_fingerprint: str,
) -> FrozenTechnicalLevel:
    level = FrozenTechnicalLevel(
        level_id=_identifier(level_id, "Frozen level identity"),
        level_type=_level_type(level_type),
        price=_positive(price, "Frozen level price"),
        known_at=_timestamp(known_at, "Frozen level known-at"),
        origin=_identifier(origin, "Frozen level origin"),
        evidence_fingerprint=_sha256(
            evidence_fingerprint, "Frozen level evidence fingerprint"
        ),
    )
    return level


def evaluate_technical_structure(
    request: TechnicalStructureRequest,
    *,
    policy: TechnicalStructurePolicy | None = None,
) -> TechnicalStructureEvaluation:
    """Evaluate an existing opportunity without mutating caller-owned evidence."""

    selected_policy = policy or current_policy()
    validate_policy(selected_policy)
    request = _canonical_request(request)
    validate_request_identity(request)
    policy_fp = policy_fingerprint(selected_policy)
    bars, provisional_count, admission = _admit_bars(request, selected_policy)
    evidence_fp = _input_evidence_fingerprint(request)

    if admission is not None:
        reason, abstention = admission
        opinion = _abstained_opinion(
            request,
            policy_fp=policy_fp,
            evidence_fp=evidence_fp,
            reason_code=reason,
            abstention_reason=abstention,
        )
        return _finalize_evaluation(
            request=request,
            policy_fp=policy_fp,
            evidence_fp=evidence_fp,
            provisional_count=provisional_count,
            structures=(),
            opinion=opinion,
        )

    pivots = detect_pivots(bars, request.as_of, selected_policy)
    volatility = _volatility_context(bars, len(bars) - 1, selected_policy)
    levels = _reference_levels(request, bars, pivots, volatility, selected_policy)
    structures: list[TechnicalStructureInstance] = []
    structures.extend(
        _support_resistance_instances(request, bars, levels, volatility, selected_policy)
    )
    structures.extend(
        _compression_expansion_instances(request, bars, volatility, selected_policy)
    )
    structures.extend(
        _breakout_instances(request, bars, levels, volatility, selected_policy)
    )
    structures.extend(_vwap_instances(request, bars, volatility, selected_policy))
    structures.extend(
        _continuation_instances(request, bars, pivots, volatility, selected_policy)
    )
    structures.extend(
        _double_extreme_instances(request, bars, pivots, volatility, selected_policy)
    )
    structures.extend(
        _head_shoulders_instances(request, bars, pivots, volatility, selected_policy)
    )
    structures.extend(
        _exhaustion_instances(request, bars, pivots, structures, volatility, selected_policy)
    )
    canonical = _canonical_instances(structures)
    opinion = _build_opinion(request, canonical, policy_fp, evidence_fp)
    return _finalize_evaluation(
        request=request,
        policy_fp=policy_fp,
        evidence_fp=evidence_fp,
        provisional_count=provisional_count,
        structures=canonical,
        opinion=opinion,
    )


def detect_pivots(
    bars: Sequence[TechnicalStructureBar],
    as_of: datetime | str,
    policy: TechnicalStructurePolicy,
) -> tuple[TechnicalPivot, ...]:
    cutoff = _parse_timestamp(_timestamp(as_of, "Pivot as-of"))
    left = policy.pivot_left_bars
    right = policy.pivot_right_bars
    pivots: list[TechnicalPivot] = []
    for index in range(left, len(bars) - right):
        current = bars[index]
        confirmation = bars[index + right]
        if confirmation.completed_at is None or (
            _parse_timestamp(confirmation.completed_at) > cutoff
        ):
            continue
        prior = bars[index - left : index]
        later = bars[index + 1 : index + right + 1]
        if all(current.high > item.high for item in (*prior, *later)):
            pivots.append(_build_pivot(PIVOT_HIGH, current, confirmation, right))
        if all(current.low < item.low for item in (*prior, *later)):
            pivots.append(_build_pivot(PIVOT_LOW, current, confirmation, right))
    return tuple(sorted(pivots, key=lambda item: (item.timestamp, item.pivot_type)))


def technical_structure_experiment_preregistration(
    policy: TechnicalStructurePolicy,
) -> dict[str, Any]:
    """Return a RESEARCH-GOV-001-compatible single-variant preregistration plan."""

    return {
        "experimentId": "tech-structure-v2-software-validation",
        "experimentVersion": SPECIALIST_VERSION,
        "researchTiming": "PROSPECTIVE",
        "researchIntent": "CONFIRMATORY",
        "hypothesis": (
            "Frozen deterministic geometry can be reproduced without look-ahead, "
            "unsafe price basis, or mutation of the observed Momentum opportunity."
        ),
        "policyFingerprint": policy_fingerprint(policy),
        "searchMethod": "SINGLE_PREREGISTERED_VARIANT",
        "plannedVariantCount": 1,
        "outcomeOptimizationAuthorized": False,
        "holdoutState": "NOT_APPLICABLE",
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY_NONE,
    }


def research_data_basis_compatibility(
    request: TechnicalStructureRequest,
) -> dict[str, str | bool]:
    """Describe the narrow RESEARCH-DATA-002 admission contract without importing it."""

    normalized = _canonical_request(request)
    basis_map = {
        SAME_SESSION_RAW_PROVIDER: "RAW_PROVIDER",
        SPLIT_ADJUSTED_ANALYSIS: "SPLIT_ADJUSTED",
        TOTAL_RETURN_ADJUSTED: "TOTAL_RETURN_ADJUSTED",
        UNKNOWN_PRICE_BASIS: "UNKNOWN",
    }
    admitted = (
        normalized.basis_verified
        and normalized.corporate_action_safe
        and normalized.price_basis != UNKNOWN_PRICE_BASIS
        and normalized.security_identity_status in {SESSION_BOUND, DURABLE}
    )
    return {
        "sourceContract": "research-data-basis-v1",
        "requestedBasis": basis_map[normalized.price_basis],
        "basisVerification": "VERIFIED" if normalized.basis_verified else "UNKNOWN",
        "securityIdentityStatus": normalized.security_identity_status,
        "corporateActionSafe": normalized.corporate_action_safe,
        "admissionStatus": (
            "SAFE_FOR_RAW_ANALYSIS"
            if admitted and normalized.price_basis == SAME_SESSION_RAW_PROVIDER
            else "SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS"
            if admitted
            else "DATA_BASIS_UNCERTAIN"
        ),
        "authority": "RESEARCH_DATA_ADMISSION_ONLY",
        "executionAuthority": "NONE",
    }


def evaluation_json_bytes(evaluation: TechnicalStructureEvaluation) -> bytes:
    validate_evaluation(evaluation)
    return _canonical_json(_wire(evaluation))


def structure_instance_to_wire(instance: TechnicalStructureInstance) -> dict[str, Any]:
    validate_structure_instance(instance)
    return _wire(instance)


def validate_policy(policy: TechnicalStructurePolicy) -> None:
    if not isinstance(policy, TechnicalStructurePolicy):
        raise TechnicalStructureError("Technical policy is malformed.")
    _identifier(policy.policy_version, "Policy version")
    integer_fields = (
        "pivot_left_bars",
        "pivot_right_bars",
        "atr_window",
        "minimum_bars",
        "expected_interval_seconds",
        "max_evidence_age_seconds",
        "level_min_touches",
        "breakout_failure_horizon_bars",
        "compression_window",
    )
    for name in integer_fields:
        value = getattr(policy, name)
        if type(value) is not int or value <= 0:
            raise TechnicalStructureError(f"Policy {name} must be positive integer data.")
    ratio_fields = (
        "level_tolerance_atr",
        "breakout_buffer_atr",
        "retest_tolerance_atr",
        "compression_ratio_max",
        "expansion_range_multiple",
        "minimum_retracement",
        "maximum_retracement",
        "double_extreme_tolerance_atr",
        "double_valley_depth_atr",
        "shoulder_tolerance_atr",
        "head_prominence_atr",
        "neckline_tolerance_atr",
        "vwap_tolerance_atr",
        "exhaustion_extension_atr",
        "exhaustion_volume_multiple",
    )
    for name in ratio_fields:
        _positive(getattr(policy, name), f"Policy {name}")
    if not 0 < policy.compression_ratio_max < 1:
        raise TechnicalStructureError("Compression ratio must be between zero and one.")
    if not 0 < policy.minimum_retracement < policy.maximum_retracement < 1:
        raise TechnicalStructureError("Retracement policy is contradictory.")
    if policy.minimum_bars <= policy.atr_window:
        raise TechnicalStructureError("Minimum bars must exceed the ATR window.")
    sessions = tuple(_session(item) for item in policy.full_evaluation_sessions)
    if sessions != policy.full_evaluation_sessions or len(set(sessions)) != len(sessions):
        raise TechnicalStructureError("Policy sessions are not canonical and unique.")


def validate_structure_bar(bar: TechnicalStructureBar) -> None:
    if not isinstance(bar, TechnicalStructureBar):
        raise TechnicalStructureError("Technical bar is malformed.")
    symbol = _symbol(bar.symbol)
    timestamp = _timestamp(bar.timestamp, "Bar timestamp")
    source = _identifier(bar.source, "Bar source")
    expected_id = _fingerprint(
        "technical-structure-bar-identity-v2",
        {"symbol": symbol, "timestamp": timestamp, "source": source},
    )
    if bar.bar_id != expected_id:
        raise TechnicalStructureError("Technical bar identity is invalid.")
    completion = (
        _timestamp(bar.completed_at, "Bar completion timestamp")
        if bar.completed_at is not None
        else None
    )
    if bar.completed and completion is None:
        raise TechnicalStructureError("Completed bar requires completion time.")
    if not bar.completed and completion is not None:
        raise TechnicalStructureError("Forming bar cannot claim completion time.")
    if completion is not None and _parse_timestamp(completion) <= _parse_timestamp(timestamp):
        raise TechnicalStructureError("Bar completion must follow its economic timestamp.")
    open_price = _positive(bar.open, "Bar open")
    high = _positive(bar.high, "Bar high")
    low = _positive(bar.low, "Bar low")
    close = _positive(bar.close, "Bar close")
    if high < max(open_price, close, low) or low > min(open_price, close, high):
        raise TechnicalStructureError("Technical bar contains contradictory OHLC values.")
    _optional_nonnegative(bar.volume, "Bar volume")
    _session(bar.session)
    _price_basis(bar.price_basis)
    _sha256(bar.evidence_fingerprint, "Bar evidence fingerprint")


def validate_request_identity(request: TechnicalStructureRequest) -> None:
    if not isinstance(request, TechnicalStructureRequest):
        raise TechnicalStructureError("Technical request is malformed.")
    _sha256(request.opportunity_id, "Opportunity identity")
    _optional_identifier(request.candidate_id, "Candidate identity")
    _optional_sha256(request.setup_id, "Setup identity")
    _optional_sha256(request.trade_plan_id, "TradePlan identity")
    if request.setup_id is not None and request.candidate_id is None:
        raise TechnicalStructureError("Setup identity requires candidate identity.")
    if request.trade_plan_id is not None and request.setup_id is None:
        raise TechnicalStructureError("TradePlan identity requires setup identity.")
    _symbol(request.symbol)
    if request.thesis_direction not in {BULLISH, BEARISH}:
        raise TechnicalStructureError("Technical thesis direction is unsupported.")
    as_of = _parse_timestamp(_timestamp(request.as_of, "Request as-of"))
    expires = _parse_timestamp(_timestamp(request.expires_at, "Request expiration"))
    if expires <= as_of:
        raise TechnicalStructureError("Technical request expires at or before as-of.")
    _session(request.session)
    _price_basis(request.price_basis)
    if request.security_identity_status not in SECURITY_IDENTITY_STATES:
        raise TechnicalStructureError("Security identity status is unsupported.")
    _boolean(request.basis_verified, "Basis verification")
    _boolean(request.corporate_action_safe, "Corporate-action safety")
    _optional_sha256(
        request.expected_trade_plan_fingerprint,
        "Expected TradePlan fingerprint",
    )
    for level in request.frozen_levels:
        if not isinstance(level, FrozenTechnicalLevel):
            raise TechnicalStructureError("Frozen level is malformed.")
        build_frozen_level(**asdict(level))


def _canonical_request(request: TechnicalStructureRequest) -> TechnicalStructureRequest:
    if not isinstance(request, TechnicalStructureRequest):
        raise TechnicalStructureError("Technical request is malformed.")
    return replace(
        request,
        opportunity_id=_sha256(request.opportunity_id, "Opportunity identity"),
        candidate_id=_optional_identifier(request.candidate_id, "Candidate identity"),
        setup_id=_optional_sha256(request.setup_id, "Setup identity"),
        trade_plan_id=_optional_sha256(request.trade_plan_id, "TradePlan identity"),
        symbol=_symbol(request.symbol),
        thesis_direction=str(request.thesis_direction).strip().upper(),
        as_of=_timestamp(request.as_of, "Request as-of"),
        expires_at=_timestamp(request.expires_at, "Request expiration"),
        session=_session(request.session),
        price_basis=_price_basis(request.price_basis),
        security_identity_status=str(request.security_identity_status).strip().upper(),
        frozen_levels=tuple(
            build_frozen_level(
                level_id=item.level_id,
                level_type=item.level_type,
                price=item.price,
                known_at=item.known_at,
                origin=item.origin,
                evidence_fingerprint=item.evidence_fingerprint,
            )
            for item in request.frozen_levels
        ),
        expected_trade_plan_fingerprint=_optional_sha256(
            request.expected_trade_plan_fingerprint,
            "Expected TradePlan fingerprint",
        ),
    )


def validate_structure_instance(instance: TechnicalStructureInstance) -> None:
    if not isinstance(instance, TechnicalStructureInstance):
        raise TechnicalStructureError("Technical structure instance is malformed.")
    if instance.schema_version != SCHEMA_VERSION:
        raise TechnicalStructureError("Technical structure schema is unsupported.")
    if instance.structure_version != STRUCTURE_VERSION:
        raise TechnicalStructureError("Technical structure version is unsupported.")
    expected_id = _structure_identity(instance)
    if instance.structure_id != expected_id:
        raise TechnicalStructureError("Technical structure identity is invalid.")
    expected_fp = _fingerprint(
        "technical-structure-instance-fingerprint-v2",
        _wire(replace(instance, fingerprint="")),
    )
    if instance.fingerprint != expected_fp:
        raise TechnicalStructureError("Technical structure fingerprint is invalid.")
    if _parse_timestamp(instance.known_at) < _parse_timestamp(instance.detected_at):
        raise TechnicalStructureError("Structure known-at precedes its economic event.")
    if instance.confirmation_state not in {
        CONFIRMED_STRUCTURE,
        POTENTIAL_STRUCTURE,
        AMBIGUOUS_SAME_BAR,
    }:
        raise TechnicalStructureError("Structure confirmation state is unsupported.")
    if instance.invalidation_state not in {ACTIVE, INVALIDATED, NOT_APPLICABLE}:
        raise TechnicalStructureError("Structure invalidation state is unsupported.")
    if tuple(sorted(set(instance.reason_codes))) != instance.reason_codes:
        raise TechnicalStructureError("Structure reason codes are not canonical.")


def validate_evaluation(evaluation: TechnicalStructureEvaluation) -> None:
    if not isinstance(evaluation, TechnicalStructureEvaluation):
        raise TechnicalStructureError("Technical evaluation is malformed.")
    if evaluation.schema_version != SCHEMA_VERSION:
        raise TechnicalStructureError("Technical evaluation schema is unsupported.")
    if evaluation.specialist_version != SPECIALIST_VERSION:
        raise TechnicalStructureError("Technical specialist version is unsupported.")
    for instance in evaluation.structures:
        validate_structure_instance(instance)
        if instance.known_at > evaluation.as_of:
            raise TechnicalStructureError("Technical evaluation contains future structure.")
        if instance.policy_fingerprint != evaluation.policy_fingerprint:
            raise TechnicalStructureError("Structure policy identity drifted from evaluation.")
    if evaluation.opinion.specialist_id != SPECIALIST_ID or (
        evaluation.opinion.specialist_version != SPECIALIST_VERSION
    ):
        raise TechnicalStructureError("Technical evaluation used the wrong specialist identity.")
    if evaluation.opinion.policy_fingerprint != evaluation.policy_fingerprint:
        raise TechnicalStructureError("Opinion policy identity drifted from evaluation.")
    if evaluation.opinion.input_evidence_fingerprint != evaluation.input_evidence_fingerprint:
        raise TechnicalStructureError("Opinion evidence identity drifted from evaluation.")
    if evaluation.opinion.as_of != evaluation.as_of:
        raise TechnicalStructureError("Opinion as-of drifted from evaluation.")
    validate_opinion_target_identity(
        evaluation.opinion,
        opportunity_id=evaluation.opinion.opportunity_id,
        candidate_id=evaluation.opinion.candidate_id,
        setup_id=evaluation.opinion.setup_id,
        trade_plan_id=evaluation.opinion.trade_plan_id,
    )
    expected = _fingerprint(
        "technical-structure-evaluation-v2",
        _wire(replace(evaluation, fingerprint="")),
    )
    if evaluation.fingerprint != expected:
        raise TechnicalStructureError("Technical evaluation fingerprint is invalid.")


def _admit_bars(
    request: TechnicalStructureRequest,
    policy: TechnicalStructurePolicy,
) -> tuple[tuple[TechnicalStructureBar, ...], int, tuple[str, str] | None]:
    if not request.bars:
        return (), 0, ("NO_CANDLE_EVIDENCE", "INSUFFICIENT_EVIDENCE")
    as_of = _parse_timestamp(request.as_of)
    completed: list[TechnicalStructureBar] = []
    provisional_count = 0
    identities: dict[str, TechnicalStructureBar] = {}
    previous_time: datetime | None = None
    session_dates: set[str] = set()
    for bar in request.bars:
        validate_structure_bar(bar)
        if bar.symbol != request.symbol:
            raise TechnicalStructureError("Technical evidence crossed symbol identity.")
        if bar.session != request.session:
            raise TechnicalStructureError("Technical evidence crossed market session.")
        if bar.price_basis != request.price_basis:
            raise TechnicalStructureError("Technical evidence crossed price basis.")
        if bar.bar_id in identities:
            if identities[bar.bar_id] == bar:
                raise TechnicalStructureError("Technical bar identity is duplicated.")
            raise TechnicalStructureError("Technical bar identity is contradictory.")
        identities[bar.bar_id] = bar
        economic_time = _parse_timestamp(bar.timestamp)
        if economic_time > as_of:
            raise TechnicalStructureError("Technical evaluation attempted future-bar use.")
        if previous_time is not None and economic_time <= previous_time:
            raise TechnicalStructureError("Technical bars are out of order.")
        previous_time = economic_time
        session_dates.add(economic_time.date().isoformat())
        if not bar.completed:
            provisional_count += 1
            continue
        if bar.completed_at is None:
            raise TechnicalStructureError("Completed bar lacks completion identity.")
        if _parse_timestamp(bar.completed_at) > as_of:
            raise TechnicalStructureError("Technical evaluation attempted future-bar use.")
        completed.append(bar)

    if request.session not in policy.full_evaluation_sessions:
        reason = (
            "TRUE_04_TO_07_PATH_UNOBSERVED"
            if request.session == PREMARKET and not policy.premarket_full_path_observed
            else "UNSUPPORTED_SESSION"
        )
        return tuple(completed), provisional_count, (reason, "UNSUPPORTED_SESSION")
    if request.price_basis == UNKNOWN_PRICE_BASIS or not request.basis_verified:
        return tuple(completed), provisional_count, (
            "DATA_BASIS_UNCERTAIN",
            "DATA_BASIS_UNCERTAIN",
        )
    if not request.corporate_action_safe:
        return tuple(completed), provisional_count, (
            "CORPORATE_ACTION_DISCONTINUITY",
            "DATA_BASIS_UNCERTAIN",
        )
    if len(session_dates) > 1:
        if request.price_basis == SAME_SESSION_RAW_PROVIDER:
            return tuple(completed), provisional_count, (
                "CROSS_SESSION_RAW_BASIS_UNSAFE",
                "DATA_BASIS_UNCERTAIN",
            )
        if request.security_identity_status != DURABLE:
            return tuple(completed), provisional_count, (
                "DURABLE_SECURITY_IDENTITY_REQUIRED",
                "DATA_BASIS_UNCERTAIN",
            )
    elif request.price_basis == SAME_SESSION_RAW_PROVIDER and (
        request.security_identity_status not in {SESSION_BOUND, DURABLE}
    ):
        return tuple(completed), provisional_count, (
            "SESSION_SECURITY_IDENTITY_UNRESOLVED",
            "DATA_BASIS_UNCERTAIN",
        )
    if len(completed) < policy.minimum_bars:
        return tuple(completed), provisional_count, (
            "INSUFFICIENT_COMPLETED_BARS",
            "INSUFFICIENT_EVIDENCE",
        )
    for first, second in zip(completed, completed[1:]):
        delta = (_parse_timestamp(second.timestamp) - _parse_timestamp(first.timestamp)).total_seconds()
        same_date = first.timestamp[:10] == second.timestamp[:10]
        if same_date and delta != policy.expected_interval_seconds:
            return tuple(completed), provisional_count, (
                "MISSING_REQUIRED_INTERVAL",
                "INSUFFICIENT_EVIDENCE",
            )
    latest = _parse_timestamp(completed[-1].completed_at or completed[-1].timestamp)
    age = (as_of - latest).total_seconds()
    if age < 0:
        raise TechnicalStructureError("Technical evidence is future-dated.")
    if age > policy.max_evidence_age_seconds:
        return tuple(completed), provisional_count, (
            "STALE_CANDLE_EVIDENCE",
            "STALE_EVIDENCE",
        )
    return tuple(completed), provisional_count, None


def _build_pivot(
    pivot_type: str,
    bar: TechnicalStructureBar,
    confirmation_bar: TechnicalStructureBar,
    confirmation_horizon: int,
) -> TechnicalPivot:
    known_at = confirmation_bar.completed_at
    if known_at is None:
        raise TechnicalStructureError("Pivot confirmation bar is incomplete.")
    price = bar.high if pivot_type == PIVOT_HIGH else bar.low
    evidence_fp = _fingerprint(
        "technical-pivot-evidence-v2",
        {
            "economicBar": bar.evidence_fingerprint,
            "confirmationBar": confirmation_bar.evidence_fingerprint,
        },
    )
    identity = _fingerprint(
        "technical-pivot-identity-v2",
        {
            "type": pivot_type,
            "barId": bar.bar_id,
            "knownAt": known_at,
            "horizon": confirmation_horizon,
        },
    )
    seed = TechnicalPivot(
        pivot_id=identity,
        pivot_type=pivot_type,
        timestamp=bar.timestamp,
        known_at=known_at,
        price=price,
        bar_id=bar.bar_id,
        confirmation_horizon_bars=confirmation_horizon,
        evidence_fingerprint=evidence_fp,
        fingerprint="",
    )
    return replace(
        seed,
        fingerprint=_fingerprint("technical-pivot-fingerprint-v2", _wire(seed)),
    )


def _reference_levels(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    pivots: Sequence[TechnicalPivot],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> tuple[TechnicalReferenceLevel, ...]:
    levels: list[TechnicalReferenceLevel] = []
    for item in request.frozen_levels:
        if _parse_timestamp(item.known_at) > _parse_timestamp(request.as_of):
            raise TechnicalStructureError("Frozen level was not known at evaluation time.")
        levels.append(
            _build_reference_level(
                level_type=item.level_type,
                price=item.price,
                origin=CALLER_FROZEN_LEVEL,
                first_known_at=item.known_at,
                known_at=item.known_at,
                touch_count=1,
                tolerance=volatility.atr * policy.level_tolerance_atr,
                invalidation_state=ACTIVE,
                evidence_fingerprint=item.evidence_fingerprint,
                source_identity=item.level_id,
            )
        )
    for pivot_type, level_type in ((PIVOT_LOW, SUPPORT), (PIVOT_HIGH, RESISTANCE)):
        candidates = [item for item in pivots if item.pivot_type == pivot_type]
        clusters: list[list[TechnicalPivot]] = []
        for pivot in candidates:
            matching = next(
                (
                    cluster
                    for cluster in clusters
                    if abs(pivot.price - fmean(item.price for item in cluster))
                    <= volatility.atr * policy.level_tolerance_atr
                ),
                None,
            )
            if matching is None:
                clusters.append([pivot])
            else:
                matching.append(pivot)
        for cluster in clusters:
            if len(cluster) < policy.level_min_touches:
                continue
            price = fmean(item.price for item in cluster)
            tolerance = volatility.atr * policy.level_tolerance_atr
            latest_close = bars[-1].close
            invalid = (
                latest_close < price - tolerance
                if level_type == SUPPORT
                else latest_close > price + tolerance
            )
            levels.append(
                _build_reference_level(
                    level_type=level_type,
                    price=price,
                    origin=PIVOT_CLUSTER,
                    first_known_at=min(item.known_at for item in cluster),
                    known_at=sorted(item.known_at for item in cluster)[
                        policy.level_min_touches - 1
                    ],
                    touch_count=len(cluster),
                    tolerance=tolerance,
                    invalidation_state=INVALIDATED if invalid else ACTIVE,
                    evidence_fingerprint=_fingerprint(
                        "technical-level-cluster-evidence-v2",
                        [item.fingerprint for item in cluster],
                    ),
                    source_identity=_fingerprint(
                        "technical-level-cluster-source-v2",
                        [item.pivot_id for item in cluster],
                    ),
                )
            )
    by_id = {item.level_id: item for item in levels}
    return tuple(sorted(by_id.values(), key=lambda item: (item.known_at, item.level_type, item.price)))


def _build_reference_level(
    *,
    level_type: str,
    price: float,
    origin: str,
    first_known_at: str,
    known_at: str,
    touch_count: int,
    tolerance: float,
    invalidation_state: str,
    evidence_fingerprint: str,
    source_identity: str,
) -> TechnicalReferenceLevel:
    identity_payload = {
        "levelType": level_type,
        "price": _rounded(price),
        "origin": origin,
        "knownAt": known_at,
        "sourceIdentity": source_identity,
    }
    seed = TechnicalReferenceLevel(
        level_id=_fingerprint("technical-reference-level-identity-v2", identity_payload),
        level_type=_level_type(level_type),
        price=_rounded(price),
        origin=_identifier(origin, "Reference-level origin"),
        first_known_at=_timestamp(first_known_at, "Reference-level first known-at"),
        known_at=_timestamp(known_at, "Reference-level known-at"),
        touch_count=touch_count,
        tolerance_basis="ATR",
        tolerance_value=_rounded(tolerance),
        invalidation_state=invalidation_state,
        evidence_fingerprint=_sha256(
            evidence_fingerprint, "Reference-level evidence fingerprint"
        ),
        fingerprint="",
    )
    return replace(
        seed,
        fingerprint=_fingerprint("technical-reference-level-fingerprint-v2", _wire(seed)),
    )


def _support_resistance_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    levels: Sequence[TechnicalReferenceLevel],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    current = bars[-1]
    instances: list[TechnicalStructureInstance] = []
    for level in levels:
        distance = current.close - level.price
        nearby = abs(distance) <= max(volatility.atr, level.tolerance_value * 3)
        if not nearby:
            continue
        direction = (
            BULLISH
            if level.level_type == SUPPORT and current.close >= level.price - level.tolerance_value
            else BEARISH
            if level.level_type == RESISTANCE and current.close <= level.price + level.tolerance_value
            else NO_DIRECTION
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=SUPPORT_RESISTANCE,
                direction=direction,
                detected_at=current.timestamp,
                known_at=current.completed_at or current.timestamp,
                bars=(current,),
                levels=(level,),
                pivots=(),
                measurements=(
                    _measurement("DISTANCE_TO_LEVEL", abs(distance), current.close, volatility),
                ),
                volatility=volatility,
                confirmation_state=CONFIRMED_STRUCTURE,
                invalidation_state=level.invalidation_state,
                reason_codes=(f"NEARBY_{level.level_type}",),
                policy=policy,
            )
        )
    return instances


def _compression_expansion_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    window = policy.compression_window
    instances: list[TechnicalStructureInstance] = []
    for index in range(window, len(bars)):
        compression = bars[index - window : index]
        expansion = bars[index]
        half = window // 2
        early = fmean(item.high - item.low for item in compression[:half])
        late = fmean(item.high - item.low for item in compression[-half:])
        if early <= 0 or late / early > policy.compression_ratio_max:
            continue
        expansion_range = expansion.high - expansion.low
        if expansion_range < late * policy.expansion_range_multiple:
            continue
        upper = max(item.high for item in compression)
        lower = min(item.low for item in compression)
        if expansion.close > upper:
            direction = BULLISH
            level_type = RESISTANCE
            level_price = upper
        elif expansion.close < lower:
            direction = BEARISH
            level_type = SUPPORT
            level_price = lower
        else:
            continue
        level = _derived_level(
            level_type,
            level_price,
            expansion,
            volatility.atr * policy.level_tolerance_atr,
            "COMPRESSION_BOUNDARY",
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=COMPRESSION_EXPANSION,
                direction=direction,
                detected_at=expansion.timestamp,
                known_at=expansion.completed_at or expansion.timestamp,
                bars=(*compression, expansion),
                levels=(level,),
                pivots=(),
                measurements=(
                    _measurement("COMPRESSION_RATIO", late / early, 1.0, volatility),
                    _measurement(
                        "EXPANSION_RANGE", expansion_range, expansion.close, volatility
                    ),
                ),
                volatility=volatility,
                confirmation_state=CONFIRMED_STRUCTURE,
                invalidation_state=ACTIVE,
                reason_codes=("RANGE_COMPRESSION", "RANGE_EXPANSION"),
                policy=policy,
            )
        )
    return instances


def _breakout_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    levels: Sequence[TechnicalReferenceLevel],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    instances: list[TechnicalStructureInstance] = []
    for level in levels:
        known = _parse_timestamp(level.known_at)
        eligible = [bar for bar in bars if _parse_timestamp(bar.timestamp) >= known]
        if len(eligible) < 2:
            continue
        direction = BULLISH if level.level_type == RESISTANCE else BEARISH
        buffer = volatility.atr * policy.breakout_buffer_atr
        tolerance = max(level.tolerance_value, volatility.atr * policy.retest_tolerance_atr)
        breakout_index: int | None = None
        for index, bar in enumerate(eligible):
            crossed = (
                bar.close > level.price + buffer
                if direction == BULLISH
                else bar.close < level.price - buffer
            )
            if not crossed:
                continue
            same_bar_invalid = (
                bar.low < level.price - tolerance
                if direction == BULLISH
                else bar.high > level.price + tolerance
            )
            if same_bar_invalid:
                instances.append(
                    _build_instance(
                        request=request,
                        structure_type=FAILED_BREAKOUT,
                        direction=_opposite_direction(direction),
                        detected_at=bar.timestamp,
                        known_at=bar.completed_at or bar.timestamp,
                        bars=(bar,),
                        levels=(level,),
                        pivots=(),
                        measurements=(
                            _measurement(
                                "BREAKOUT_DISTANCE", abs(bar.close - level.price), bar.close, volatility
                            ),
                        ),
                        volatility=volatility,
                        confirmation_state=AMBIGUOUS_SAME_BAR,
                        invalidation_state=INVALIDATED,
                        reason_codes=("BREAKOUT_AND_INVALIDATION_SAME_BAR",),
                        policy=policy,
                    )
                )
                breakout_index = None
                break
            breakout_index = index
            break
        if breakout_index is None:
            continue
        breakout = eligible[breakout_index]
        horizon = eligible[
            breakout_index + 1 : breakout_index + 1 + policy.breakout_failure_horizon_bars
        ]
        failure = next(
            (
                item
                for item in horizon
                if (
                    item.close < level.price - tolerance
                    if direction == BULLISH
                    else item.close > level.price + tolerance
                )
            ),
            None,
        )
        if failure is not None:
            instances.append(
                _build_instance(
                    request=request,
                    structure_type=FAILED_BREAKOUT,
                    direction=_opposite_direction(direction),
                    detected_at=breakout.timestamp,
                    known_at=failure.completed_at or failure.timestamp,
                    bars=(breakout, failure),
                    levels=(level,),
                    pivots=(),
                    measurements=(
                        _measurement(
                            "FAILURE_DISTANCE", abs(failure.close - level.price), failure.close, volatility
                        ),
                    ),
                    volatility=volatility,
                    confirmation_state=CONFIRMED_STRUCTURE,
                    invalidation_state=INVALIDATED,
                    reason_codes=("PREEXISTING_LEVEL_BROKEN", "LEVEL_FAILED_WITHIN_HORIZON"),
                    policy=policy,
                )
            )
            continue
        retest_index = next(
            (
                index
                for index in range(breakout_index + 1, len(eligible) - 1)
                if (
                    eligible[index].low <= level.price + tolerance
                    and eligible[index].close >= level.price - tolerance
                    if direction == BULLISH
                    else eligible[index].high >= level.price - tolerance
                    and eligible[index].close <= level.price + tolerance
                )
            ),
            None,
        )
        if retest_index is None:
            continue
        retest = eligible[retest_index]
        confirmation = eligible[retest_index + 1]
        holds = (
            confirmation.close > level.price + buffer
            if direction == BULLISH
            else confirmation.close < level.price - buffer
        )
        ambiguous = holds and (
            confirmation.low < level.price - tolerance
            if direction == BULLISH
            else confirmation.high > level.price + tolerance
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=BREAKOUT_RETEST,
                direction=direction,
                detected_at=breakout.timestamp,
                known_at=confirmation.completed_at or confirmation.timestamp,
                bars=(breakout, retest, confirmation),
                levels=(level,),
                pivots=(),
                measurements=(
                    _measurement(
                        "RETEST_DEPTH", abs(retest.close - level.price), retest.close, volatility
                    ),
                ),
                volatility=volatility,
                confirmation_state=(
                    AMBIGUOUS_SAME_BAR
                    if ambiguous
                    else CONFIRMED_STRUCTURE
                    if holds
                    else POTENTIAL_STRUCTURE
                ),
                invalidation_state=(INVALIDATED if ambiguous or not holds else ACTIVE),
                reason_codes=(
                    "PREEXISTING_LEVEL_BROKEN",
                    "LEVEL_RETESTED",
                    "RETEST_CONFIRMATION_AND_INVALIDATION_SAME_BAR"
                    if ambiguous
                    else "RETEST_HELD"
                    if holds
                    else "RETEST_NOT_CONFIRMED",
                ),
                policy=policy,
            )
        )
    return instances


def _vwap_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    if any(item.volume is None for item in bars):
        return []
    source_bars = [_as_v1_bar(item) for item in bars]
    vwaps = cumulative_vwap_values(source_bars)
    tolerance = volatility.atr * policy.vwap_tolerance_atr
    instances: list[TechnicalStructureInstance] = []
    for index in range(1, len(bars) - 1):
        previous_vwap = vwaps[index - 1]
        current_vwap = vwaps[index]
        next_vwap = vwaps[index + 1]
        if previous_vwap is None or current_vwap is None or next_vwap is None:
            continue
        previous = bars[index - 1]
        current = bars[index]
        confirmation = bars[index + 1]
        structure_type: str | None = None
        direction = NO_DIRECTION
        holds = False
        if previous.close < previous_vwap - tolerance and current.close > current_vwap + tolerance:
            structure_type = VWAP_RECLAIM
            direction = BULLISH
            holds = confirmation.close > next_vwap + tolerance
        elif previous.close > previous_vwap + tolerance and current.close < current_vwap - tolerance:
            structure_type = VWAP_LOSS
            direction = BEARISH
            holds = confirmation.close < next_vwap - tolerance
        if structure_type is None:
            continue
        ambiguous = holds and (
            confirmation.low < next_vwap - tolerance
            if direction == BULLISH
            else confirmation.high > next_vwap + tolerance
        )
        level = _derived_level(
            SUPPORT if direction == BULLISH else RESISTANCE,
            current_vwap,
            current,
            tolerance,
            BAR_DERIVED_VWAP,
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=structure_type,
                direction=direction,
                detected_at=current.timestamp,
                known_at=confirmation.completed_at or confirmation.timestamp,
                bars=(previous, current, confirmation),
                levels=(level,),
                pivots=(),
                measurements=(
                    _measurement("VWAP_DISTANCE", abs(current.close - current_vwap), current.close, volatility),
                ),
                volatility=volatility,
                confirmation_state=(
                    AMBIGUOUS_SAME_BAR
                    if ambiguous
                    else CONFIRMED_STRUCTURE
                    if holds
                    else POTENTIAL_STRUCTURE
                ),
                invalidation_state=(INVALIDATED if ambiguous or not holds else ACTIVE),
                reason_codes=(
                    "BAR_DERIVED_VWAP",
                    "VWAP_CROSS",
                    "VWAP_HOLD_AND_LOSS_SAME_BAR"
                    if ambiguous
                    else "VWAP_HOLD_CONFIRMED"
                    if holds
                    else "VWAP_HOLD_UNCONFIRMED",
                ),
                policy=policy,
            )
        )
    return instances


def _continuation_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    pivots: Sequence[TechnicalPivot],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    instances: list[TechnicalStructureInstance] = []
    for first, middle, last in zip(pivots, pivots[1:], pivots[2:]):
        if (
            first.pivot_type == PIVOT_LOW
            and middle.pivot_type == PIVOT_HIGH
            and last.pivot_type == PIVOT_LOW
            and last.price > first.price
        ):
            impulse = middle.price - first.price
            retracement = (middle.price - last.price) / impulse if impulse > 0 else -1
            if not policy.minimum_retracement <= retracement <= policy.maximum_retracement:
                continue
            confirmation = _first_bar_after(
                bars,
                last.known_at,
                lambda item: item.close > middle.price + volatility.atr * policy.breakout_buffer_atr,
            )
            if confirmation is not None:
                instances.append(
                    _continuation_instance(
                        request,
                        HIGHER_LOW_CONTINUATION,
                        BULLISH,
                        (first, middle, last),
                        confirmation,
                        retracement,
                        volatility,
                        policy,
                    )
                )
        if (
            first.pivot_type == PIVOT_HIGH
            and middle.pivot_type == PIVOT_LOW
            and last.pivot_type == PIVOT_HIGH
            and last.price < first.price
        ):
            impulse = first.price - middle.price
            retracement = (last.price - middle.price) / impulse if impulse > 0 else -1
            if not policy.minimum_retracement <= retracement <= policy.maximum_retracement:
                continue
            confirmation = _first_bar_after(
                bars,
                last.known_at,
                lambda item: item.close < middle.price - volatility.atr * policy.breakout_buffer_atr,
            )
            if confirmation is not None:
                instances.append(
                    _continuation_instance(
                        request,
                        LOWER_HIGH_BREAKDOWN,
                        BEARISH,
                        (first, middle, last),
                        confirmation,
                        retracement,
                        volatility,
                        policy,
                    )
                )
    return instances


def _continuation_instance(
    request: TechnicalStructureRequest,
    structure_type: str,
    direction: str,
    pivots: tuple[TechnicalPivot, TechnicalPivot, TechnicalPivot],
    confirmation: TechnicalStructureBar,
    retracement: float,
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> TechnicalStructureInstance:
    level_price = pivots[1].price
    ambiguous = (
        confirmation.low < pivots[-1].price - volatility.atr * policy.level_tolerance_atr
        if direction == BULLISH
        else confirmation.high > pivots[-1].price + volatility.atr * policy.level_tolerance_atr
    )
    level = _derived_level(
        RESISTANCE if direction == BULLISH else SUPPORT,
        level_price,
        confirmation,
        volatility.atr * policy.level_tolerance_atr,
        "CONTINUATION_TRIGGER",
    )
    return _build_instance(
        request=request,
        structure_type=structure_type,
        direction=direction,
        detected_at=pivots[-1].timestamp,
        known_at=confirmation.completed_at or confirmation.timestamp,
        bars=(confirmation,),
        levels=(level,),
        pivots=pivots,
        measurements=(
            _measurement("RETRACEMENT", retracement, 1.0, volatility),
        ),
        volatility=volatility,
        confirmation_state=AMBIGUOUS_SAME_BAR if ambiguous else CONFIRMED_STRUCTURE,
        invalidation_state=INVALIDATED if ambiguous else ACTIVE,
        reason_codes=(
            "ORDERED_PIVOT_SEQUENCE",
            "CONTINUATION_AND_INVALIDATION_SAME_BAR"
            if ambiguous
            else "CONTINUATION_CONFIRMED",
        ),
        policy=policy,
    )


def _double_extreme_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    pivots: Sequence[TechnicalPivot],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    instances: list[TechnicalStructureInstance] = []
    for first, middle, second in zip(pivots, pivots[1:], pivots[2:]):
        top = (
            first.pivot_type == PIVOT_HIGH
            and middle.pivot_type == PIVOT_LOW
            and second.pivot_type == PIVOT_HIGH
        )
        bottom = (
            first.pivot_type == PIVOT_LOW
            and middle.pivot_type == PIVOT_HIGH
            and second.pivot_type == PIVOT_LOW
        )
        if not top and not bottom:
            continue
        extreme_difference = abs(first.price - second.price)
        if extreme_difference > volatility.atr * policy.double_extreme_tolerance_atr:
            continue
        valley_depth = (
            min(first.price, second.price) - middle.price
            if top
            else middle.price - max(first.price, second.price)
        )
        if valley_depth < volatility.atr * policy.double_valley_depth_atr:
            continue
        direction = BEARISH if top else BULLISH
        structure_type = DOUBLE_TOP if top else DOUBLE_BOTTOM
        confirmation = _first_bar_after(
            bars,
            second.known_at,
            (
                (lambda item: item.close < middle.price - volatility.atr * policy.breakout_buffer_atr)
                if top
                else (lambda item: item.close > middle.price + volatility.atr * policy.breakout_buffer_atr)
            ),
        )
        confirmed = confirmation is not None
        ambiguous = confirmation is not None and (
            confirmation.high
            > max(first.price, second.price)
            + volatility.atr * policy.double_extreme_tolerance_atr
            if top
            else confirmation.low
            < min(first.price, second.price)
            - volatility.atr * policy.double_extreme_tolerance_atr
        )
        known_at = (
            confirmation.completed_at or confirmation.timestamp
            if confirmation is not None
            else second.known_at
        )
        evidence_bars = (confirmation,) if confirmation is not None else ()
        level = _derived_level(
            SUPPORT if top else RESISTANCE,
            middle.price,
            confirmation or bars[-1],
            volatility.atr * policy.neckline_tolerance_atr,
            "DOUBLE_EXTREME_NECKLINE",
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=structure_type,
                direction=direction,
                detected_at=second.timestamp,
                known_at=known_at,
                bars=evidence_bars,
                levels=(level,),
                pivots=(first, middle, second),
                measurements=(
                    _measurement("EXTREME_DIFFERENCE", extreme_difference, second.price, volatility),
                    _measurement("VALLEY_DEPTH", valley_depth, middle.price, volatility),
                ),
                volatility=volatility,
                confirmation_state=(
                    AMBIGUOUS_SAME_BAR
                    if ambiguous
                    else CONFIRMED_STRUCTURE
                    if confirmed
                    else POTENTIAL_STRUCTURE
                ),
                invalidation_state=INVALIDATED if ambiguous else ACTIVE,
                reason_codes=(
                    "DOUBLE_EXTREME_GEOMETRY",
                    "NECKLINE_AND_INVALIDATION_SAME_BAR"
                    if ambiguous
                    else "NECKLINE_CONFIRMED"
                    if confirmed
                    else "NECKLINE_UNCONFIRMED",
                ),
                policy=policy,
            )
        )
    return instances


def _head_shoulders_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    pivots: Sequence[TechnicalPivot],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    instances: list[TechnicalStructureInstance] = []
    for index in range(len(pivots) - 4):
        group = tuple(pivots[index : index + 5])
        top = tuple(item.pivot_type for item in group) == (
            PIVOT_HIGH,
            PIVOT_LOW,
            PIVOT_HIGH,
            PIVOT_LOW,
            PIVOT_HIGH,
        )
        inverse = tuple(item.pivot_type for item in group) == (
            PIVOT_LOW,
            PIVOT_HIGH,
            PIVOT_LOW,
            PIVOT_HIGH,
            PIVOT_LOW,
        )
        if not top and not inverse:
            continue
        left, neck_one, head, neck_two, right = group
        shoulder_difference = abs(left.price - right.price)
        if shoulder_difference > volatility.atr * policy.shoulder_tolerance_atr:
            continue
        prominence = (
            head.price - max(left.price, right.price)
            if top
            else min(left.price, right.price) - head.price
        )
        if prominence < volatility.atr * policy.head_prominence_atr:
            continue
        neckline = (neck_one.price + neck_two.price) / 2.0
        confirmation = _first_bar_after(
            bars,
            right.known_at,
            (
                (
                    lambda item: item.close
                    < neckline - volatility.atr * policy.breakout_buffer_atr
                )
                if top
                else (
                    lambda item: item.close
                    > neckline + volatility.atr * policy.breakout_buffer_atr
                )
            ),
        )
        confirmed = confirmation is not None
        ambiguous = confirmation is not None and (
            confirmation.high > right.price + volatility.atr * policy.shoulder_tolerance_atr
            if top
            else confirmation.low < right.price - volatility.atr * policy.shoulder_tolerance_atr
        )
        direction = BEARISH if top else BULLISH
        structure_type = HEAD_AND_SHOULDERS if top else INVERSE_HEAD_AND_SHOULDERS
        level = _derived_level(
            SUPPORT if top else RESISTANCE,
            neckline,
            confirmation or bars[-1],
            volatility.atr * policy.neckline_tolerance_atr,
            "HEAD_SHOULDERS_NECKLINE",
        )
        instances.append(
            _build_instance(
                request=request,
                structure_type=structure_type,
                direction=direction,
                detected_at=right.timestamp,
                known_at=(
                    confirmation.completed_at or confirmation.timestamp
                    if confirmation is not None
                    else right.known_at
                ),
                bars=(confirmation,) if confirmation is not None else (),
                levels=(level,),
                pivots=group,
                measurements=(
                    _measurement("SHOULDER_DIFFERENCE", shoulder_difference, right.price, volatility),
                    _measurement("HEAD_PROMINENCE", prominence, head.price, volatility),
                    _measurement("NECKLINE_SLOPE", neck_two.price - neck_one.price, neckline, volatility),
                ),
                volatility=volatility,
                confirmation_state=(
                    AMBIGUOUS_SAME_BAR
                    if ambiguous
                    else CONFIRMED_STRUCTURE
                    if confirmed
                    else POTENTIAL_STRUCTURE
                ),
                invalidation_state=INVALIDATED if ambiguous else ACTIVE,
                reason_codes=(
                    "FIVE_PIVOT_GEOMETRY",
                    "NECKLINE_AND_INVALIDATION_SAME_BAR"
                    if ambiguous
                    else "NECKLINE_CONFIRMED"
                    if confirmed
                    else "NECKLINE_UNCONFIRMED",
                ),
                policy=policy,
            )
        )
    return instances


def _exhaustion_instances(
    request: TechnicalStructureRequest,
    bars: Sequence[TechnicalStructureBar],
    pivots: Sequence[TechnicalPivot],
    structures: Sequence[TechnicalStructureInstance],
    volatility: VolatilityContext,
    policy: TechnicalStructurePolicy,
) -> list[TechnicalStructureInstance]:
    failures = [
        item
        for item in structures
        if item.structure_type == FAILED_BREAKOUT
        and item.confirmation_state == CONFIRMED_STRUCTURE
    ]
    reasons: list[str] = []
    if len(failures) >= 2:
        reasons.append("REPEATED_BREAKOUT_FAILURE")
    recent_highs = [item for item in pivots if item.pivot_type == PIVOT_HIGH][-3:]
    if len(recent_highs) == 3 and recent_highs[0].price > recent_highs[1].price > recent_highs[2].price:
        reasons.append("PROGRESSIVELY_WEAKER_HIGHS")
    context_window = bars[-min(len(bars), max(policy.atr_window * 2, 6)) :]
    baseline_bars = context_window[: max(2, len(context_window) - 3)]
    if baseline_bars:
        baseline = fmean(item.close for item in baseline_bars)
        if request.thesis_direction == BULLISH:
            peak = max(item.high for item in context_window)
            if (
                peak - baseline >= volatility.atr * policy.exhaustion_extension_atr
                and peak - bars[-1].close >= volatility.atr * 0.50
            ):
                reasons.append("EXTREME_EXTENSION_FAILURE")
        else:
            trough = min(item.low for item in context_window)
            if (
                baseline - trough >= volatility.atr * policy.exhaustion_extension_atr
                and bars[-1].close - trough >= volatility.atr * 0.50
            ):
                reasons.append("EXTREME_EXTENSION_FAILURE")
    volume_context = _volume_context(bars)
    price_progress = abs(bars[-1].close - bars[-2].close)
    if (
        volume_context.relative_volume is not None
        and volume_context.relative_volume >= policy.exhaustion_volume_multiple
        and price_progress <= volatility.atr * 0.10
    ):
        reasons.append("HIGH_VOLUME_WITHOUT_PROGRESS")
    if not reasons:
        return []
    latest = bars[-1]
    return [
        _build_instance(
            request=request,
            structure_type=TECHNICAL_EXHAUSTION,
            direction=request.thesis_direction,
            detected_at=latest.timestamp,
            known_at=latest.completed_at or latest.timestamp,
            bars=context_window,
            levels=(),
            pivots=tuple(recent_highs),
            measurements=(
                _measurement("LATEST_PRICE_PROGRESS", price_progress, latest.close, volatility),
            ),
            volatility=volatility,
            confirmation_state=CONFIRMED_STRUCTURE,
            invalidation_state=NOT_APPLICABLE,
            reason_codes=tuple(reasons),
            policy=policy,
        )
    ]


def _build_opinion(
    request: TechnicalStructureRequest,
    structures: Sequence[TechnicalStructureInstance],
    policy_fp: str,
    evidence_fp: str,
) -> SpecialistOpinion:
    confirmed = [item for item in structures if item.confirmation_state == CONFIRMED_STRUCTURE]
    exhausted = any(item.structure_type == TECHNICAL_EXHAUSTION for item in confirmed)
    supports = [item for item in confirmed if item.direction == request.thesis_direction]
    contradicts = [
        item
        for item in confirmed
        if item.direction in {BULLISH, BEARISH} and item.direction != request.thesis_direction
    ]
    if exhausted:
        code = STRUCTURE_EXHAUSTED
        bias = NEUTRAL
        reasons = ("INSTRUMENT_STRUCTURE_EXHAUSTED",)
    elif supports and contradicts:
        code = STRUCTURE_NEUTRAL
        bias = NEUTRAL
        reasons = ("CONFLICTING_CONFIRMED_STRUCTURES",)
    elif contradicts:
        code = STRUCTURE_CONTRADICTS
        bias = contradicts[-1].direction
        reasons = ("CONFIRMED_STRUCTURE_OPPOSES_THESIS",)
    elif supports:
        code = STRUCTURE_SUPPORTS
        bias = request.thesis_direction
        reasons = ("CONFIRMED_STRUCTURE_ALIGNS_WITH_THESIS",)
    else:
        code = STRUCTURE_NEUTRAL
        bias = NEUTRAL
        reasons = ("NO_CONFIRMED_DIRECTIONAL_STRUCTURE",)
    evidence = _opinion_evidence_reference(request, evidence_fp)
    families = {"CANDLE_STRUCTURE", "PRICE_MOMENTUM"}
    if any(
        item.structure_type in {VWAP_RECLAIM, VWAP_LOSS}
        or "HIGH_VOLUME_WITHOUT_PROGRESS" in item.reason_codes
        for item in structures
    ):
        families.add("VOLUME")
    return build_specialist_opinion(
        specialist_id=SPECIALIST_ID,
        specialist_version=SPECIALIST_VERSION,
        opportunity_id=request.opportunity_id,
        candidate_id=request.candidate_id,
        setup_id=request.setup_id,
        trade_plan_id=request.trade_plan_id,
        as_of=request.as_of,
        expires_at=request.expires_at,
        research_identity=RESEARCH_IDENTITY,
        policy_fingerprint=policy_fp,
        evaluation_status=EVALUATED,
        opinion_code=code,
        directional_bias=bias,
        evidence_refs=(evidence,),
        feature_families=tuple(sorted(families)),
        reason_codes=reasons,
        explanation=(
            f"Detected {len(structures)} technical structure instance(s), including "
            f"{len(confirmed)} confirmed instance(s), from completed caller-supplied bars."
        ),
    )


def _abstained_opinion(
    request: TechnicalStructureRequest,
    *,
    policy_fp: str,
    evidence_fp: str,
    reason_code: str,
    abstention_reason: str,
) -> SpecialistOpinion:
    references = (
        (_opinion_evidence_reference(request, evidence_fp),)
        if request.bars
        else ()
    )
    return build_specialist_opinion(
        specialist_id=SPECIALIST_ID,
        specialist_version=SPECIALIST_VERSION,
        opportunity_id=request.opportunity_id,
        candidate_id=request.candidate_id,
        setup_id=request.setup_id,
        trade_plan_id=request.trade_plan_id,
        as_of=request.as_of,
        expires_at=request.expires_at,
        research_identity=RESEARCH_IDENTITY,
        policy_fingerprint=policy_fp,
        evaluation_status=ABSTAINED,
        opinion_code=NO_OPINION,
        directional_bias=NO_DIRECTION,
        evidence_refs=references,
        feature_families=("CANDLE_STRUCTURE",) if references else (),
        reason_codes=(reason_code,),
        abstention_reason=abstention_reason,
        explanation=f"Technical Structure abstained: {reason_code}.",
    )


def _build_instance(
    *,
    request: TechnicalStructureRequest,
    structure_type: str,
    direction: str,
    detected_at: str,
    known_at: str,
    bars: Sequence[TechnicalStructureBar],
    levels: Sequence[TechnicalReferenceLevel],
    pivots: Sequence[TechnicalPivot],
    measurements: Sequence[GeometryMeasurement],
    volatility: VolatilityContext,
    confirmation_state: str,
    invalidation_state: str,
    reason_codes: Sequence[str],
    policy: TechnicalStructurePolicy,
) -> TechnicalStructureInstance:
    evidence_times = [item.timestamp for item in bars] + [item.timestamp for item in pivots]
    if not evidence_times:
        evidence_times = [detected_at]
    evidence_fps = tuple(
        sorted(
            {
                *(item.evidence_fingerprint for item in bars),
                *(item.evidence_fingerprint for item in pivots),
                *(item.evidence_fingerprint for item in levels),
            }
        )
    )
    seed = TechnicalStructureInstance(
        schema_version=SCHEMA_VERSION,
        structure_id="",
        structure_version=STRUCTURE_VERSION,
        structure_type=_structure_type(structure_type),
        symbol=request.symbol,
        opportunity_id=request.opportunity_id,
        setup_id=request.setup_id,
        direction=direction,
        detected_at=_timestamp(detected_at, "Structure event time"),
        known_at=_timestamp(known_at, "Structure known-at"),
        evidence_start=min(evidence_times),
        evidence_end=max(evidence_times),
        confirmation_state=confirmation_state,
        invalidation_state=invalidation_state,
        reference_levels=tuple(sorted(levels, key=lambda item: item.level_id)),
        pivots=tuple(sorted(pivots, key=lambda item: (item.timestamp, item.pivot_type))),
        geometry_measurements=tuple(sorted(measurements, key=lambda item: item.name)),
        volatility_normalization=volatility,
        volume_context=_volume_context(bars),
        price_basis=request.price_basis,
        session=request.session,
        policy_fingerprint=policy_fingerprint(policy),
        evidence_fingerprints=evidence_fps,
        reason_codes=tuple(sorted(set(reason_codes))),
        fingerprint="",
    )
    with_id = replace(seed, structure_id=_structure_identity(seed))
    complete = replace(
        with_id,
        fingerprint=_fingerprint(
            "technical-structure-instance-fingerprint-v2",
            _wire(with_id),
        ),
    )
    validate_structure_instance(complete)
    return complete


def _finalize_evaluation(
    *,
    request: TechnicalStructureRequest,
    policy_fp: str,
    evidence_fp: str,
    provisional_count: int,
    structures: Sequence[TechnicalStructureInstance],
    opinion: SpecialistOpinion,
) -> TechnicalStructureEvaluation:
    validate_opinion_target_identity(
        opinion,
        opportunity_id=request.opportunity_id,
        candidate_id=request.candidate_id,
        setup_id=request.setup_id,
        trade_plan_id=request.trade_plan_id,
    )
    seed = TechnicalStructureEvaluation(
        schema_version=SCHEMA_VERSION,
        specialist_version=SPECIALIST_VERSION,
        policy_fingerprint=policy_fp,
        input_evidence_fingerprint=opinion.input_evidence_fingerprint,
        as_of=request.as_of,
        provisional_bar_count=provisional_count,
        structures=tuple(structures),
        opinion=opinion,
        fingerprint="",
    )
    complete = replace(
        seed,
        fingerprint=_fingerprint("technical-structure-evaluation-v2", _wire(seed)),
    )
    validate_evaluation(complete)
    return complete


def _structure_identity(instance: TechnicalStructureInstance) -> str:
    return _fingerprint(
        "technical-structure-instance-identity-v2",
        {
            "version": instance.structure_version,
            "type": instance.structure_type,
            "symbol": instance.symbol,
            "opportunityId": instance.opportunity_id,
            "setupId": instance.setup_id,
            "direction": instance.direction,
            "detectedAt": instance.detected_at,
            "knownAt": instance.known_at,
            "evidenceStart": instance.evidence_start,
            "evidenceEnd": instance.evidence_end,
            "confirmationState": instance.confirmation_state,
            "pivots": [item.pivot_id for item in instance.pivots],
            "levels": [item.level_id for item in instance.reference_levels],
            "geometry": [_wire(item) for item in instance.geometry_measurements],
            "basis": instance.price_basis,
            "policy": instance.policy_fingerprint,
            "evidence": list(instance.evidence_fingerprints),
        },
    )


def _canonical_instances(
    instances: Sequence[TechnicalStructureInstance],
) -> tuple[TechnicalStructureInstance, ...]:
    by_id: dict[str, TechnicalStructureInstance] = {}
    for item in instances:
        validate_structure_instance(item)
        prior = by_id.get(item.structure_id)
        if prior is not None and prior != item:
            raise TechnicalStructureError("Technical structure identity is contradictory.")
        by_id[item.structure_id] = item
    return tuple(
        sorted(
            by_id.values(),
            key=lambda item: (
                item.known_at,
                item.detected_at,
                item.structure_type,
                item.structure_id,
            ),
        )
    )


def _derived_level(
    level_type: str,
    price: float,
    bar: TechnicalStructureBar,
    tolerance: float,
    origin: str,
) -> TechnicalReferenceLevel:
    return _build_reference_level(
        level_type=level_type,
        price=price,
        origin=origin,
        first_known_at=bar.completed_at or bar.timestamp,
        known_at=bar.completed_at or bar.timestamp,
        touch_count=1,
        tolerance=tolerance,
        invalidation_state=ACTIVE,
        evidence_fingerprint=bar.evidence_fingerprint,
        source_identity=bar.bar_id,
    )


def _measurement(
    name: str,
    value: float,
    price_baseline: float,
    volatility: VolatilityContext,
) -> GeometryMeasurement:
    absolute = _finite(value, f"{name} absolute")
    return GeometryMeasurement(
        name=_identifier(name, "Geometry measurement"),
        absolute=_rounded(absolute),
        percent=_rounded(absolute / price_baseline * 100.0) if price_baseline else None,
        atr_units=_rounded(absolute / volatility.atr) if volatility.atr else None,
        recent_range_units=(
            _rounded(absolute / volatility.recent_range)
            if volatility.recent_range
            else None
        ),
    )


def _volatility_context(
    bars: Sequence[TechnicalStructureBar],
    index: int,
    policy: TechnicalStructurePolicy,
) -> VolatilityContext:
    if index < policy.atr_window:
        raise TechnicalStructureError("ATR evidence is insufficient after admission.")
    source = [_as_v1_bar(item) for item in bars]
    ranges = [
        true_range(source[position], source[position - 1])
        for position in range(index - policy.atr_window + 1, index + 1)
    ]
    atr = fmean(ranges)
    if atr <= 0:
        raise TechnicalStructureError("ATR normalization is nonpositive.")
    recent = bars[max(0, index - policy.atr_window + 1) : index + 1]
    recent_range = max(item.high for item in recent) - min(item.low for item in recent)
    return VolatilityContext(
        atr=_rounded(atr),
        atr_window=policy.atr_window,
        recent_range=_rounded(recent_range),
        as_of=bars[index].completed_at or bars[index].timestamp,
    )


def _volume_context(bars: Sequence[TechnicalStructureBar]) -> VolumeContext:
    if not bars:
        return VolumeContext(None, None, None, "UNAVAILABLE")
    current = bars[-1].volume
    prior = [item.volume for item in bars[:-1] if item.volume is not None]
    average = fmean(prior) if prior else None
    relative = current / average if current is not None and average and average > 0 else None
    return VolumeContext(
        current_volume=_rounded(current) if current is not None else None,
        average_volume=_rounded(average) if average is not None else None,
        relative_volume=_rounded(relative) if relative is not None else None,
        source="CALLER_SUPPLIED_BAR_VOLUME" if current is not None else "UNAVAILABLE",
    )


def _first_bar_after(
    bars: Sequence[TechnicalStructureBar],
    known_at: str,
    predicate: Any,
) -> TechnicalStructureBar | None:
    cutoff = _parse_timestamp(known_at)
    return next(
        (
            item
            for item in bars
            if _parse_timestamp(item.timestamp) >= cutoff and predicate(item)
        ),
        None,
    )


def _opinion_evidence_reference(
    request: TechnicalStructureRequest,
    evidence_fp: str,
):
    completed_times = [
        item.completed_at
        for item in request.bars
        if item.completed and item.completed_at is not None
    ]
    evidence_as_of = max(completed_times) if completed_times else request.as_of
    if _parse_timestamp(evidence_as_of) > _parse_timestamp(request.as_of):
        evidence_as_of = request.as_of
    return build_evidence_reference(
        evidence_id=f"technical-bars:{request.symbol}:{evidence_fp[:16]}",
        evidence_type="CANONICAL_TECHNICAL_BARS",
        source="caller-supplied-technical-evidence",
        as_of=evidence_as_of,
        fingerprint=evidence_fp,
    )


def _input_evidence_fingerprint(request: TechnicalStructureRequest) -> str:
    return _fingerprint(
        "technical-structure-input-evidence-v2",
        {
            "target": {
                "opportunityId": request.opportunity_id,
                "candidateId": request.candidate_id,
                "setupId": request.setup_id,
                "tradePlanId": request.trade_plan_id,
                "tradePlanFingerprint": request.expected_trade_plan_fingerprint,
            },
            "symbol": request.symbol,
            "asOf": request.as_of,
            "session": request.session,
            "priceBasis": request.price_basis,
            "basisVerified": request.basis_verified,
            "securityIdentityStatus": request.security_identity_status,
            "corporateActionSafe": request.corporate_action_safe,
            "bars": [_wire(item) for item in request.bars],
            "frozenLevels": [_wire(item) for item in request.frozen_levels],
        },
    )


def _as_v1_bar(bar: TechnicalStructureBar) -> TechnicalPriceBar:
    return TechnicalPriceBar(
        symbol=bar.symbol,
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume) if bar.volume is not None else None,
        source=bar.source,
    )


def _wire(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _wire(asdict(value))
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _fingerprint(domain: str, value: Any) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + _canonical_json(value)).hexdigest()


def _timestamp(value: datetime | str, label: str) -> str:
    parsed = _parse_timestamp(value, label)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: datetime | str, label: str = "Timestamp") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TechnicalStructureError(f"{label} is invalid.") from exc
    else:
        raise TechnicalStructureError(f"{label} is invalid.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TechnicalStructureError(f"{label} requires a UTC offset.")
    return parsed


def _identifier(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not _IDENTIFIER.fullmatch(normalized):
        raise TechnicalStructureError(f"{label} is invalid.")
    return normalized


def _optional_identifier(value: Any, label: str) -> str | None:
    return None if value is None else _identifier(value, label)


def _sha256(value: Any, label: str) -> str:
    normalized = str(value).strip().lower() if value is not None else ""
    if not _SHA256.fullmatch(normalized):
        raise TechnicalStructureError(f"{label} is invalid.")
    return normalized


def _optional_sha256(value: Any, label: str) -> str | None:
    return None if value is None else _sha256(value, label)


def _symbol(value: Any) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if not _SYMBOL.fullmatch(normalized):
        raise TechnicalStructureError("Technical symbol is invalid.")
    return normalized


def _session(value: Any) -> str:
    normalized = str(value).strip().upper()
    if normalized not in SESSIONS:
        raise TechnicalStructureError("Market session is unsupported.")
    return normalized


def _price_basis(value: Any) -> str:
    normalized = str(value).strip().upper()
    if normalized not in PRICE_BASES:
        raise TechnicalStructureError("Analysis price basis is unsupported.")
    return normalized


def _level_type(value: Any) -> str:
    normalized = str(value).strip().upper()
    if normalized not in {SUPPORT, RESISTANCE}:
        raise TechnicalStructureError("Reference-level type is unsupported.")
    return normalized


def _structure_type(value: Any) -> str:
    normalized = str(value).strip().upper()
    supported = {
        COMPRESSION_EXPANSION,
        BREAKOUT_RETEST,
        FAILED_BREAKOUT,
        VWAP_RECLAIM,
        VWAP_LOSS,
        HIGHER_LOW_CONTINUATION,
        LOWER_HIGH_BREAKDOWN,
        DOUBLE_TOP,
        DOUBLE_BOTTOM,
        SUPPORT_RESISTANCE,
        HEAD_AND_SHOULDERS,
        INVERSE_HEAD_AND_SHOULDERS,
        TECHNICAL_EXHAUSTION,
    }
    if normalized not in supported:
        raise TechnicalStructureError("Technical structure type is unsupported.")
    return normalized


def _opposite_direction(direction: str) -> str:
    if direction == BULLISH:
        return BEARISH
    if direction == BEARISH:
        return BULLISH
    raise TechnicalStructureError("Directional structure has no opposite direction.")


def _finite(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TechnicalStructureError(f"{label} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise TechnicalStructureError(f"{label} must be finite.")
    return result


def _positive(value: Any, label: str) -> float:
    result = _finite(value, label)
    if result <= 0:
        raise TechnicalStructureError(f"{label} must be positive.")
    return result


def _optional_nonnegative(value: Any, label: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, label)
    if result < 0:
        raise TechnicalStructureError(f"{label} cannot be negative.")
    return result


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise TechnicalStructureError(f"{label} must be boolean.")
    return value


def _rounded(value: float, digits: int = 8) -> float:
    return round(float(value), digits)
