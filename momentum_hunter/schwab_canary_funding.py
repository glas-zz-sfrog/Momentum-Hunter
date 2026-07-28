from __future__ import annotations

"""Nontransmitting settled-cash and account-restriction canary gate."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Callable, Final

from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    AccountIsolationPolicy,
    SchwabAccount,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    SchwabBalances,
    SchwabReadOnlyAdapter,
    require_bound_hash,
    validate_account_response,
)


CANARY_FUNDING_SCHEMA_VERSION: Final = "SCHWAB_CANARY_FUNDING_GATE_V1"
CURRENT_BALANCE_SOURCE: Final = "SCHWAB_READ_ONLY_BALANCES_V1"
RESTRICTIONS_CLEAR: Final = "CLEAR"
RESTRICTIONS_BLOCKED: Final = "BLOCKED"
RESTRICTIONS_UNAVAILABLE: Final = "UNAVAILABLE"
RESTRICTION_STATES: Final = frozenset(
    {
        RESTRICTIONS_CLEAR,
        RESTRICTIONS_BLOCKED,
        RESTRICTIONS_UNAVAILABLE,
    }
)


class CanaryFundingGateError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryFundingRequirement:
    requirement_id: str
    maximum_debit: float
    minimum_cash_reserve: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirement_id",
            _normalize_identifier(self.requirement_id, field="requirement ID"),
        )
        if (
            not _is_finite_number(self.maximum_debit)
            or self.maximum_debit <= 0
        ):
            raise CanaryFundingGateError(
                "Maximum canary debit must be finite and greater than zero."
            )
        if (
            not _is_finite_number(self.minimum_cash_reserve)
            or self.minimum_cash_reserve < 0
        ):
            raise CanaryFundingGateError(
                "Minimum cash reserve must be finite and non-negative."
            )
        required_cash = self.maximum_debit + self.minimum_cash_reserve
        if not _is_finite_number(required_cash):
            raise CanaryFundingGateError(
                "Total required canary cash must be finite."
            )

    @property
    def required_settled_cash(self) -> float:
        return self.maximum_debit + self.minimum_cash_reserve


@dataclass(frozen=True)
class CanaryFundingPolicy:
    expected_source: str
    max_observation_age_seconds: float
    max_collection_duration_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expected_source",
            _normalize_identifier(self.expected_source, field="evidence source"),
        )
        for value, field in (
            (
                self.max_observation_age_seconds,
                "Maximum funding-observation age",
            ),
            (
                self.max_collection_duration_seconds,
                "Maximum funding-collection duration",
            ),
        ):
            if not _is_finite_number(value) or value <= 0:
                raise CanaryFundingGateError(
                    f"{field} must be finite and greater than zero."
                )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryFundingGateError(
                "Maximum future clock skew must be finite and non-negative."
            )


@dataclass(frozen=True, repr=False)
class CanaryFundingObservation:
    request_started_at: str
    observed_at: str
    source: str
    authorized_accounts: tuple[SchwabAuthorizedAccount, ...]
    account: SchwabAccount
    balances: SchwabBalances
    settled_cash: float | None
    restriction_state: str
    restriction_codes: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return (
            "CanaryFundingObservation("
            f"request_started_at={self.request_started_at!r}, "
            f"observed_at={self.observed_at!r}, "
            f"source={self.source!r}, "
            f"authorized_account_count={len(self.authorized_accounts)}, "
            f"restriction_state={self.restriction_state!r}, "
            f"restriction_count={len(self.restriction_codes)}, "
            f"settled_cash_available={self.settled_cash is not None})"
        )


@dataclass(frozen=True)
class CanaryFundingFinding:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CanaryFundingResult:
    status: str
    evaluated_at: str
    request_started_at: str
    observed_at: str
    balance_as_of: str
    source: str
    account_ending: str
    account_type: str
    requirement_id: str
    maximum_debit: float
    minimum_cash_reserve: float
    settled_cash_available: bool
    settled_cash_sufficient: bool | None
    restriction_state: str
    restriction_codes: tuple[str, ...]
    findings: tuple[CanaryFundingFinding, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_FUNDING_SCHEMA_VERSION,
            "status": self.status,
            "evaluatedAt": self.evaluated_at,
            "requestStartedAt": self.request_started_at,
            "observedAt": self.observed_at,
            "balanceAsOf": self.balance_as_of,
            "source": self.source,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "requirementId": self.requirement_id,
            "maximumDebit": self.maximum_debit,
            "minimumCashReserve": self.minimum_cash_reserve,
            "requiredSettledCash": self.maximum_debit
            + self.minimum_cash_reserve,
            "settledCashAvailable": self.settled_cash_available,
            "settledCashSufficient": self.settled_cash_sufficient,
            "cashAvailableSubstitutionAllowed": False,
            "buyingPowerSubstitutionAllowed": False,
            "restrictionState": self.restriction_state,
            "restrictionCodes": list(self.restriction_codes),
            "findings": [finding.to_dict() for finding in self.findings],
            "conclusion": (
                "CANARY_FUNDING_PASS"
                if self.passed
                else "CANARY_FUNDING_BLOCK"
            ),
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def read_current_schwab_funding_observation(
    adapter: SchwabReadOnlyAdapter,
    *,
    clock: Callable[[], datetime] | None = None,
) -> CanaryFundingObservation:
    """Read current contracts honestly; they do not expose settled cash."""

    active_clock = clock or _utc_now
    request_started_at = _require_aware_datetime(
        active_clock(),
        field="request_started_at",
    )
    accounts_before = tuple(adapter.list_authorized_accounts())
    account = adapter.get_account()
    balances = adapter.get_balances()
    accounts_after = tuple(adapter.list_authorized_accounts())
    if accounts_before != accounts_after:
        raise AccountIsolationError(
            "The authorized Schwab account identity changed during funding collection."
        )
    observed_at = _require_aware_datetime(
        active_clock(),
        field="observed_at",
    )
    return CanaryFundingObservation(
        request_started_at=request_started_at.isoformat(),
        observed_at=observed_at.isoformat(),
        source=CURRENT_BALANCE_SOURCE,
        authorized_accounts=accounts_after,
        account=account,
        balances=balances,
        settled_cash=None,
        restriction_state=RESTRICTIONS_UNAVAILABLE,
        restriction_codes=(),
    )


def evaluate_canary_funding(
    *,
    binding: SchwabAccountBinding,
    requirement: CanaryFundingRequirement,
    observation: CanaryFundingObservation,
    evaluated_at: datetime,
    policy: CanaryFundingPolicy,
) -> CanaryFundingResult:
    normalized_evaluated_at = _require_aware_datetime(
        evaluated_at,
        field="evaluated_at",
    )
    findings: list[CanaryFundingFinding] = []
    request_started_at = _parse_timestamp(
        observation.request_started_at,
        field="request start",
        code_prefix="REQUEST_START",
        findings=findings,
    )
    observed_at = _parse_timestamp(
        observation.observed_at,
        field="funding observation",
        code_prefix="OBSERVATION_TIME",
        findings=findings,
    )
    balance_as_of = _parse_timestamp(
        observation.balances.as_of,
        field="balance as-of",
        code_prefix="BALANCE_TIME",
        findings=findings,
    )
    _check_timing(
        request_started_at=request_started_at,
        observed_at=observed_at,
        balance_as_of=balance_as_of,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        findings=findings,
    )
    _check_account(
        binding=binding,
        observation=observation,
        findings=findings,
    )
    if observation.source != policy.expected_source:
        findings.append(
            CanaryFundingFinding(
                code="EVIDENCE_SOURCE_MISMATCH",
                message="Funding evidence did not come from the required source.",
            )
        )
    _check_balance_shape(observation.balances, findings=findings)
    settled_cash_sufficient = _check_settled_cash(
        observation.settled_cash,
        required=requirement.required_settled_cash,
        findings=findings,
    )
    restriction_state, restriction_codes = _check_restrictions(
        observation.restriction_state,
        observation.restriction_codes,
        findings=findings,
    )
    unique_findings = _deduplicate_findings(findings)
    return CanaryFundingResult(
        status="PASS" if not unique_findings else "BLOCK",
        evaluated_at=normalized_evaluated_at.isoformat(),
        request_started_at=observation.request_started_at,
        observed_at=observation.observed_at,
        balance_as_of=observation.balances.as_of,
        source=observation.source,
        account_ending=binding.account_number_last_four,
        account_type=binding.account_type,
        requirement_id=requirement.requirement_id,
        maximum_debit=requirement.maximum_debit,
        minimum_cash_reserve=requirement.minimum_cash_reserve,
        settled_cash_available=observation.settled_cash is not None,
        settled_cash_sufficient=settled_cash_sufficient,
        restriction_state=restriction_state,
        restriction_codes=restriction_codes,
        findings=unique_findings,
    )


def _check_account(
    *,
    binding: SchwabAccountBinding,
    observation: CanaryFundingObservation,
    findings: list[CanaryFundingFinding],
) -> None:
    try:
        AccountIsolationPolicy().validate_binding(
            binding,
            observation.authorized_accounts,
        )
        validate_account_response(binding, observation.account)
        require_bound_hash(binding, observation.balances.account_hash)
    except AccountIsolationError as exc:
        findings.append(
            CanaryFundingFinding(
                code="ACCOUNT_ISOLATION_FAILED",
                message=str(exc),
            )
        )
    if str(observation.account.status).strip().upper() != "OPEN":
        findings.append(
            CanaryFundingFinding(
                code="ACCOUNT_NOT_OPEN",
                message="The pinned canary account is not reported OPEN.",
            )
        )


def _check_balance_shape(
    balances: SchwabBalances,
    *,
    findings: list[CanaryFundingFinding],
) -> None:
    for field, value in (
        ("cash_available", balances.cash_available),
        ("buying_power", balances.buying_power),
        ("liquidation_value", balances.liquidation_value),
    ):
        if not _is_finite_number(value) or value < 0:
            findings.append(
                CanaryFundingFinding(
                    code="BALANCE_FIELD_INVALID",
                    message=f"The {field} balance field is invalid.",
                )
            )


def _check_settled_cash(
    settled_cash: float | None,
    *,
    required: float,
    findings: list[CanaryFundingFinding],
) -> bool | None:
    if settled_cash is None:
        findings.append(
            CanaryFundingFinding(
                code="SETTLED_CASH_UNAVAILABLE",
                message=(
                    "Settled cash is unavailable; cash available and buying power "
                    "cannot substitute for it."
                ),
            )
        )
        return None
    if not _is_finite_number(settled_cash) or settled_cash < 0:
        findings.append(
            CanaryFundingFinding(
                code="SETTLED_CASH_INVALID",
                message="Settled cash must be finite and non-negative.",
            )
        )
        return None
    if settled_cash < required:
        findings.append(
            CanaryFundingFinding(
                code="SETTLED_CASH_INSUFFICIENT",
                message="Settled cash does not cover the maximum debit and reserve.",
            )
        )
        return False
    return True


def _check_restrictions(
    state: str,
    codes: tuple[str, ...],
    *,
    findings: list[CanaryFundingFinding],
) -> tuple[str, tuple[str, ...]]:
    normalized_state = str(state).strip().upper()
    normalized_codes: list[str] = []
    invalid_code = False
    for code in codes:
        try:
            normalized = _normalize_identifier(code, field="restriction code")
        except CanaryFundingGateError:
            invalid_code = True
            continue
        if normalized not in normalized_codes:
            normalized_codes.append(normalized)
    if invalid_code or len(normalized_codes) != len(codes):
        findings.append(
            CanaryFundingFinding(
                code="RESTRICTION_CODES_INVALID",
                message="Restriction codes must be unique simple ASCII identifiers.",
            )
        )
    if normalized_state not in RESTRICTION_STATES:
        findings.append(
            CanaryFundingFinding(
                code="RESTRICTION_STATE_INVALID",
                message="The account restriction state is unsupported.",
            )
        )
    elif normalized_state == RESTRICTIONS_UNAVAILABLE:
        findings.append(
            CanaryFundingFinding(
                code="RESTRICTIONS_UNAVAILABLE",
                message="Account restriction evidence is unavailable.",
            )
        )
        if normalized_codes:
            findings.append(
                CanaryFundingFinding(
                    code="RESTRICTION_EVIDENCE_CONTRADICTORY",
                    message="Unavailable restriction evidence cannot contain codes.",
                )
            )
    elif normalized_state == RESTRICTIONS_BLOCKED:
        findings.append(
            CanaryFundingFinding(
                code="ACCOUNT_RESTRICTED",
                message="The canary account has one or more trading restrictions.",
            )
        )
        if not normalized_codes:
            findings.append(
                CanaryFundingFinding(
                    code="RESTRICTION_EVIDENCE_CONTRADICTORY",
                    message="A blocked restriction state requires at least one code.",
                )
            )
    elif normalized_codes:
        findings.append(
            CanaryFundingFinding(
                code="RESTRICTION_EVIDENCE_CONTRADICTORY",
                message="A clear restriction state cannot contain restriction codes.",
            )
        )
    return normalized_state, tuple(normalized_codes)


def _check_timing(
    *,
    request_started_at: datetime | None,
    observed_at: datetime | None,
    balance_as_of: datetime | None,
    evaluated_at: datetime,
    policy: CanaryFundingPolicy,
    findings: list[CanaryFundingFinding],
) -> None:
    if request_started_at is not None and observed_at is not None:
        duration = (observed_at - request_started_at).total_seconds()
        if duration < 0:
            findings.append(
                CanaryFundingFinding(
                    code="COLLECTION_CLOCK_REVERSED",
                    message="Funding collection completed before it started.",
                )
            )
        elif duration > policy.max_collection_duration_seconds:
            findings.append(
                CanaryFundingFinding(
                    code="COLLECTION_TOO_SLOW",
                    message="Funding collection exceeded the configured safety window.",
                )
            )
    _check_age(
        value=observed_at,
        evaluated_at=evaluated_at,
        max_age=policy.max_observation_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="OBSERVATION_STALE",
        future_code="OBSERVATION_FROM_FUTURE",
        label="Funding observation",
        findings=findings,
    )
    _check_age(
        value=balance_as_of,
        evaluated_at=evaluated_at,
        max_age=policy.max_observation_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="BALANCE_STALE",
        future_code="BALANCE_FROM_FUTURE",
        label="Balance evidence",
        findings=findings,
    )
    if (
        balance_as_of is not None
        and observed_at is not None
        and (balance_as_of - observed_at).total_seconds()
        > policy.max_future_skew_seconds
    ):
        findings.append(
            CanaryFundingFinding(
                code="BALANCE_AFTER_OBSERVATION",
                message="Balance evidence is later than its collection completion.",
            )
        )


def _check_age(
    *,
    value: datetime | None,
    evaluated_at: datetime,
    max_age: float,
    max_future_skew: float,
    stale_code: str,
    future_code: str,
    label: str,
    findings: list[CanaryFundingFinding],
) -> None:
    if value is None:
        return
    age = (evaluated_at - value).total_seconds()
    if age < -max_future_skew:
        findings.append(
            CanaryFundingFinding(
                code=future_code,
                message=f"{label} is later than the permitted clock skew.",
            )
        )
    elif age > max_age:
        findings.append(
            CanaryFundingFinding(
                code=stale_code,
                message=f"{label} is older than the configured safety window.",
            )
        )


def _parse_timestamp(
    value: str,
    *,
    field: str,
    code_prefix: str,
    findings: list[CanaryFundingFinding],
) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        findings.append(
            CanaryFundingFinding(
                code=f"{code_prefix}_INVALID",
                message=f"The {field} timestamp is not valid ISO 8601.",
            )
        )
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        findings.append(
            CanaryFundingFinding(
                code=f"{code_prefix}_NAIVE",
                message=f"The {field} timestamp must include a UTC offset.",
            )
        )
        return None
    return parsed


def _deduplicate_findings(
    findings: list[CanaryFundingFinding],
) -> tuple[CanaryFundingFinding, ...]:
    unique: list[CanaryFundingFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        identity = (finding.code, finding.message)
        if identity not in seen:
            seen.add(identity)
            unique.append(finding)
    return tuple(unique)


def _normalize_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanaryFundingGateError(
            f"A simple ASCII {field} is required."
        )
    normalized = value.strip().upper()
    if (
        not normalized
        or not normalized.isascii()
        or not normalized.replace("-", "").replace("_", "").isalnum()
    ):
        raise CanaryFundingGateError(
            f"A simple ASCII {field} is required."
        )
    return normalized


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise CanaryFundingGateError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryFundingGateError(f"{field} must include a UTC offset.")
    return value


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
