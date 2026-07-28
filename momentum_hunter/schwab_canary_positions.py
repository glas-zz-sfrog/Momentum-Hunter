from __future__ import annotations

"""Fail-closed position invariants for a future supervised Schwab canary.

This module can consume the existing read-only Schwab adapter, but it has no
credential, HTTP, preview, or order-transmission capability.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Callable, Final

from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    AccountIsolationPolicy,
    EXPECTED_ACCOUNT_TYPE,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    SchwabPosition,
    SchwabReadOnlyAdapter,
)


PRE_CANARY: Final = "PRE_CANARY"
CANARY_ACTIVE: Final = "CANARY_ACTIVE"
POST_CANARY: Final = "POST_CANARY"
CANARY_PHASES: Final = frozenset({PRE_CANARY, CANARY_ACTIVE, POST_CANARY})
POSITION_INVARIANT_SCHEMA_VERSION: Final = "SCHWAB_CANARY_POSITION_INVARIANT_V1"


class CanaryPositionInvariantError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryIntent:
    """Exact nontransmitting identity of one separately approved canary."""

    intent_id: str
    symbol: str
    quantity: float

    def __post_init__(self) -> None:
        intent_id = self.intent_id.strip()
        symbol = self.symbol.strip().upper()
        if (
            not intent_id
            or not intent_id.isascii()
            or not intent_id.replace("-", "").replace("_", "").isalnum()
        ):
            raise CanaryPositionInvariantError(
                "A simple ASCII canary intent ID is required."
            )
        if not symbol or not symbol.isascii() or not symbol.replace(".", "").replace("-", "").isalnum():
            raise CanaryPositionInvariantError("A valid ASCII canary symbol is required.")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise CanaryPositionInvariantError("Canary quantity must be finite and greater than zero.")
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True)
class CanaryPositionPolicy:
    """Freshness is supplied by the caller rather than hidden in the evaluator."""

    max_observation_age_seconds: float
    max_collection_duration_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not isfinite(self.max_observation_age_seconds) or self.max_observation_age_seconds <= 0:
            raise CanaryPositionInvariantError(
                "Maximum position-observation age must be finite and greater than zero."
            )
        if (
            not isfinite(self.max_collection_duration_seconds)
            or self.max_collection_duration_seconds <= 0
        ):
            raise CanaryPositionInvariantError(
                "Maximum position-collection duration must be finite and greater than zero."
            )
        if not isfinite(self.max_future_skew_seconds) or self.max_future_skew_seconds < 0:
            raise CanaryPositionInvariantError(
                "Maximum future clock skew must be finite and non-negative."
            )


@dataclass(frozen=True, repr=False)
class CanaryPositionObservation:
    request_started_at: str
    observed_at: str
    authorized_accounts: tuple[SchwabAuthorizedAccount, ...]
    positions: tuple[SchwabPosition, ...]

    def __repr__(self) -> str:
        return (
            "CanaryPositionObservation("
            f"request_started_at={self.request_started_at!r}, "
            f"observed_at={self.observed_at!r}, "
            f"authorized_account_count={len(self.authorized_accounts)}, "
            f"position_count={len(self.positions)})"
        )


@dataclass(frozen=True)
class CanaryPositionFinding:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CanaryPositionInvariantResult:
    phase: str
    status: str
    evaluated_at: str
    request_started_at: str
    observed_at: str
    collection_duration_seconds: float | None
    account_ending: str
    account_type: str
    canary_intent_id: str
    canary_symbol: str
    expected_quantity: float
    observed_canary_quantity: float | None
    observed_position_count: int
    findings: tuple[CanaryPositionFinding, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": POSITION_INVARIANT_SCHEMA_VERSION,
            "phase": self.phase,
            "status": self.status,
            "evaluatedAt": self.evaluated_at,
            "requestStartedAt": self.request_started_at,
            "observedAt": self.observed_at,
            "collectionDurationSeconds": self.collection_duration_seconds,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "canaryIntentId": self.canary_intent_id,
            "canarySymbol": self.canary_symbol,
            "expectedQuantity": self.expected_quantity,
            "observedCanaryQuantity": self.observed_canary_quantity,
            "observedPositionCount": self.observed_position_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "conclusion": (
                "POSITION_INVARIANT_PASS"
                if self.passed
                else "POSITION_INVARIANT_BLOCK"
            ),
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def read_canary_position_observation(
    adapter: SchwabReadOnlyAdapter,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CanaryPositionObservation:
    """Read account identity and positions through the existing GET-only adapter."""

    active_clock = clock or _utc_now
    request_started_at = _require_aware_datetime(
        active_clock(),
        field="request_started_at",
    )
    accounts_before = tuple(adapter.list_authorized_accounts())
    positions = tuple(adapter.get_positions())
    accounts_after = tuple(adapter.list_authorized_accounts())
    if accounts_before != accounts_after:
        raise AccountIsolationError(
            "The authorized Schwab account identity changed during position collection."
        )
    observed_at = _require_aware_datetime(active_clock(), field="observed_at")
    return CanaryPositionObservation(
        request_started_at=request_started_at.isoformat(),
        observed_at=observed_at.isoformat(),
        authorized_accounts=accounts_after,
        positions=positions,
    )


def evaluate_canary_position_invariant(
    *,
    phase: str,
    binding: SchwabAccountBinding,
    intent: CanaryIntent,
    observation: CanaryPositionObservation,
    evaluated_at: datetime,
    policy: CanaryPositionPolicy,
) -> CanaryPositionInvariantResult:
    """Evaluate one phase without mutating the observation or broker state."""

    normalized_phase = phase.strip().upper()
    if normalized_phase not in CANARY_PHASES:
        raise CanaryPositionInvariantError(
            f"Canary phase must be one of {sorted(CANARY_PHASES)}."
        )
    normalized_evaluated_at = _require_aware_datetime(
        evaluated_at,
        field="evaluated_at",
    )
    findings: list[CanaryPositionFinding] = []
    request_started_at = _parse_timestamp(
        observation.request_started_at,
        field="request start",
        code_prefix="REQUEST_START",
        findings=findings,
    )
    observed_at = _parse_timestamp(
        observation.observed_at,
        field="position observation",
        code_prefix="OBSERVATION_TIME",
        findings=findings,
    )
    collection_duration_seconds = _check_timing(
        request_started_at=request_started_at,
        observed_at=observed_at,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        findings=findings,
    )
    _check_account_isolation(
        binding=binding,
        accounts=observation.authorized_accounts,
        findings=findings,
    )

    positions_by_symbol = _validated_positions(
        binding=binding,
        positions=observation.positions,
        findings=findings,
    )
    canary_positions = positions_by_symbol.get(intent.symbol, ())
    observed_quantity = (
        canary_positions[0].quantity
        if len(canary_positions) == 1 and isfinite(canary_positions[0].quantity)
        else None
    )

    if normalized_phase in {PRE_CANARY, POST_CANARY}:
        _require_zero_positions(
            phase=normalized_phase,
            positions=observation.positions,
            findings=findings,
        )
    else:
        _require_exact_active_position(
            intent=intent,
            positions=observation.positions,
            positions_by_symbol=positions_by_symbol,
            findings=findings,
        )

    deduplicated_findings = _deduplicate_findings(findings)
    return CanaryPositionInvariantResult(
        phase=normalized_phase,
        status="PASS" if not deduplicated_findings else "BLOCK",
        evaluated_at=normalized_evaluated_at.isoformat(),
        request_started_at=observation.request_started_at,
        observed_at=observation.observed_at,
        collection_duration_seconds=collection_duration_seconds,
        account_ending=binding.account_number_last_four,
        account_type=binding.account_type,
        canary_intent_id=intent.intent_id,
        canary_symbol=intent.symbol,
        expected_quantity=intent.quantity,
        observed_canary_quantity=observed_quantity,
        observed_position_count=len(observation.positions),
        findings=deduplicated_findings,
    )


def _parse_timestamp(
    value: str,
    *,
    field: str,
    code_prefix: str,
    findings: list[CanaryPositionFinding],
) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        findings.append(
            CanaryPositionFinding(
                code=f"{code_prefix}_INVALID",
                message=f"The {field} timestamp is not valid ISO 8601.",
            )
        )
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        findings.append(
            CanaryPositionFinding(
                code=f"{code_prefix}_NAIVE",
                message=f"The {field} timestamp must include a UTC offset.",
            )
        )
        return None
    return parsed


def _check_timing(
    *,
    request_started_at: datetime | None,
    observed_at: datetime | None,
    evaluated_at: datetime,
    policy: CanaryPositionPolicy,
    findings: list[CanaryPositionFinding],
) -> float | None:
    collection_duration_seconds: float | None = None
    if request_started_at is not None and observed_at is not None:
        collection_duration_seconds = (
            observed_at - request_started_at
        ).total_seconds()
        if collection_duration_seconds < 0:
            findings.append(
                CanaryPositionFinding(
                    code="COLLECTION_CLOCK_REVERSED",
                    message="The position collection completed before it started.",
                )
            )
        elif collection_duration_seconds > policy.max_collection_duration_seconds:
            findings.append(
                CanaryPositionFinding(
                    code="COLLECTION_TOO_SLOW",
                    message="The position collection exceeded the configured safety window.",
                )
            )
    if observed_at is None:
        return collection_duration_seconds
    age_seconds = (evaluated_at - observed_at).total_seconds()
    if age_seconds < -policy.max_future_skew_seconds:
        findings.append(
            CanaryPositionFinding(
                code="OBSERVATION_FROM_FUTURE",
                message="The position observation is later than the permitted clock skew.",
            )
        )
    elif age_seconds > policy.max_observation_age_seconds:
        findings.append(
            CanaryPositionFinding(
                code="OBSERVATION_STALE",
                message="The position observation is older than the configured safety window.",
            )
        )
    return collection_duration_seconds


def _check_account_isolation(
    *,
    binding: SchwabAccountBinding,
    accounts: tuple[SchwabAuthorizedAccount, ...],
    findings: list[CanaryPositionFinding],
) -> None:
    try:
        AccountIsolationPolicy().validate_binding(binding, accounts)
    except AccountIsolationError as exc:
        findings.append(
            CanaryPositionFinding(
                code="ACCOUNT_ISOLATION_FAILED",
                message=str(exc),
            )
        )


def _validated_positions(
    *,
    binding: SchwabAccountBinding,
    positions: tuple[SchwabPosition, ...],
    findings: list[CanaryPositionFinding],
) -> dict[str, tuple[SchwabPosition, ...]]:
    grouped: dict[str, list[SchwabPosition]] = {}
    for position in positions:
        symbol = position.symbol.strip().upper()
        if position.account_hash != binding.account_hash:
            findings.append(
                CanaryPositionFinding(
                    code="POSITION_ACCOUNT_MISMATCH",
                    message="A position belongs to an account other than the pinned canary account.",
                )
            )
        if not symbol:
            findings.append(
                CanaryPositionFinding(
                    code="POSITION_SYMBOL_MISSING",
                    message="A returned position has no symbol.",
                )
            )
            continue
        if not isfinite(position.quantity):
            findings.append(
                CanaryPositionFinding(
                    code="POSITION_QUANTITY_INVALID",
                    message=f"The {symbol} position quantity is not finite.",
                )
            )
        grouped.setdefault(symbol, []).append(position)
    for symbol, items in grouped.items():
        if len(items) > 1:
            findings.append(
                CanaryPositionFinding(
                    code="DUPLICATE_POSITION_SYMBOL",
                    message=f"Multiple position records were returned for {symbol}.",
                )
            )
    return {symbol: tuple(items) for symbol, items in grouped.items()}


def _require_zero_positions(
    *,
    phase: str,
    positions: tuple[SchwabPosition, ...],
    findings: list[CanaryPositionFinding],
) -> None:
    if positions:
        findings.append(
            CanaryPositionFinding(
                code="ZERO_POSITION_INVARIANT_FAILED",
                message=f"{phase} requires exactly zero positions; received {len(positions)}.",
            )
        )


def _require_exact_active_position(
    *,
    intent: CanaryIntent,
    positions: tuple[SchwabPosition, ...],
    positions_by_symbol: dict[str, tuple[SchwabPosition, ...]],
    findings: list[CanaryPositionFinding],
) -> None:
    if len(positions) != 1:
        findings.append(
            CanaryPositionFinding(
                code="ACTIVE_POSITION_COUNT_FAILED",
                message=f"CANARY_ACTIVE requires exactly one position; received {len(positions)}.",
            )
        )
    matching = positions_by_symbol.get(intent.symbol, ())
    if len(matching) != 1:
        findings.append(
            CanaryPositionFinding(
                code="CANARY_POSITION_MISSING",
                message=f"CANARY_ACTIVE requires one exact {intent.symbol} position.",
            )
        )
    for symbol in sorted(positions_by_symbol):
        if symbol != intent.symbol:
            findings.append(
                CanaryPositionFinding(
                    code="UNEXPECTED_POSITION",
                    message=f"CANARY_ACTIVE does not permit the {symbol} position.",
                )
            )
    if len(matching) != 1:
        return
    quantity = matching[0].quantity
    if not isfinite(quantity):
        return
    if quantity <= 0:
        findings.append(
            CanaryPositionFinding(
                code="CANARY_POSITION_NOT_LONG",
                message="The canary position must be a positive long quantity.",
            )
        )
    if quantity != intent.quantity:
        findings.append(
            CanaryPositionFinding(
                code="CANARY_QUANTITY_MISMATCH",
                message=(
                    "The canary position quantity does not match the exact approved intent "
                    f"({quantity} observed, {intent.quantity} expected)."
                ),
            )
        )


def _deduplicate_findings(
    findings: list[CanaryPositionFinding],
) -> tuple[CanaryPositionFinding, ...]:
    unique: list[CanaryPositionFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        identity = (finding.code, finding.message)
        if identity not in seen:
            seen.add(identity)
            unique.append(finding)
    return tuple(unique)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise CanaryPositionInvariantError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryPositionInvariantError(f"{field} must include a UTC offset.")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
