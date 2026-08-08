from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable

from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    AccountIsolationPolicy,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    SchwabBalances,
    SchwabPosition,
    require_bound_hash,
)


ACCOUNT_ALLOCATION_SCHEMA_VERSION = 1
ACCOUNT_ALLOCATION_PROFILE = "account-aware-fixed-unit-risk-v1"
ALLOCATION_AUTHORIZED = "AUTHORIZED"
ALLOCATION_BLOCKED = "BLOCKED"
EXPECTED_ACCOUNT_TYPE = "INDIVIDUAL_CASH"
EXPECTED_ACCOUNT_ENDING = "2573"
TRANSMISSION_UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AccountAllocationPolicy:
    """Explicit sizing limits. Missing limits are blockers, never defaults."""

    policy_id: str = ""
    fixed_unit_risk_dollars: float | None = None
    max_position_notional_dollars: float | None = None
    minimum_cash_reserve_dollars: float | None = None
    max_total_open_risk_dollars: float | None = None
    daily_loss_limit_dollars: float | None = None
    max_open_positions: int | None = None
    max_balance_age_seconds: int | None = None
    whole_shares_only: bool = True
    schema_version: int = ACCOUNT_ALLOCATION_SCHEMA_VERSION
    profile: str = ACCOUNT_ALLOCATION_PROFILE

    @property
    def fingerprint(self) -> str:
        return payload_fingerprint(asdict(self))


@dataclass(frozen=True)
class AccountAllocationContext:
    """Redacted, read-only account state captured for one allocation decision."""

    binding_fingerprint: str = ""
    account_ending: str = ""
    account_type: str = ""
    authorized_account_count: int = 0
    cash_available: float | None = None
    buying_power: float | None = None
    liquidation_value: float | None = None
    committed_notional: float | None = None
    committed_open_risk: float | None = None
    open_position_count: int | None = None
    realized_pnl_today: float | None = None
    provider_timestamp: str = ""
    portfolio_timestamp: str = ""
    receipt_timestamp: str = ""
    source: str = ""
    portfolio_source: str = ""
    order_transmission: str = TRANSMISSION_UNAVAILABLE

    @property
    def fingerprint(self) -> str:
        return payload_fingerprint(asdict(self))


@dataclass(frozen=True)
class AccountAllocationEvidence:
    trade_plan_id: str
    decision_at: str
    status: str
    quantity: int
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    risk_per_share: float | None
    position_notional: float | None
    total_risk: float | None
    target_reward: float | None
    reward_risk_ratio: float | None
    effective_cash_available: float | None
    effective_risk_budget: float | None
    policy_fingerprint: str
    account_context_fingerprint: str
    blockers: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = ACCOUNT_ALLOCATION_SCHEMA_VERSION
    profile: str = ACCOUNT_ALLOCATION_PROFILE

    @property
    def authorized(self) -> bool:
        return self.status == ALLOCATION_AUTHORIZED and self.quantity > 0 and not self.blockers

    @property
    def fingerprint(self) -> str:
        return payload_fingerprint(asdict(self))


@dataclass(frozen=True)
class AccountAllocationDecision:
    policy: AccountAllocationPolicy
    context: AccountAllocationContext
    evidence: AccountAllocationEvidence

    @property
    def fingerprint(self) -> str:
        return payload_fingerprint(asdict(self))


@dataclass(frozen=True)
class AccountPortfolioSnapshot:
    """Strategy commitments captured before an allocation decision."""

    committed_notional: float
    committed_open_risk: float
    open_position_count: int
    realized_pnl_today: float
    observed_at: str
    source: str


class FrozenAccountAllocationSource:
    """Allocate from one already captured account context; never performs I/O."""

    def __init__(
        self,
        *,
        policy: AccountAllocationPolicy,
        context: AccountAllocationContext,
    ) -> None:
        self.policy = policy
        self.context = context

    def allocate(
        self,
        *,
        symbol: str,
        trade_plan_id: str,
        entry_price: float | None,
        stop_price: float | None,
        target_price: float | None,
        decision_at: datetime,
    ) -> AccountAllocationDecision:
        del symbol
        return build_account_allocation_decision(
            trade_plan_id=trade_plan_id,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            policy=self.policy,
            context=self.context,
            decision_at=decision_at,
        )


def build_schwab_account_allocation_context(
    *,
    binding: SchwabAccountBinding,
    authorized_accounts: Iterable[SchwabAuthorizedAccount],
    balances: SchwabBalances,
    broker_positions: Iterable[SchwabPosition],
    portfolio: AccountPortfolioSnapshot,
    received_at: datetime,
) -> AccountAllocationContext:
    """Convert validated read-only Schwab evidence into a redacted allocator context."""

    accounts = tuple(authorized_accounts)
    AccountIsolationPolicy().validate_binding(binding, accounts)
    require_bound_hash(binding, balances.account_hash)
    positions = tuple(broker_positions)
    for position in positions:
        require_bound_hash(binding, position.account_hash)
    if positions:
        raise AccountIsolationError(
            "Account allocation stopped because the bound Schwab account has an unexpected position."
        )
    binding_fingerprint = payload_fingerprint(
        {
            "profile": "schwab-bound-account-allocation-v1",
            "account_hash": binding.account_hash,
            "account_ending": binding.account_number_last_four,
            "account_type": binding.account_type,
        }
    )
    return AccountAllocationContext(
        binding_fingerprint=binding_fingerprint,
        account_ending=binding.account_number_last_four,
        account_type=binding.account_type,
        authorized_account_count=len(accounts),
        cash_available=balances.cash_available,
        buying_power=balances.buying_power,
        liquidation_value=balances.liquidation_value,
        committed_notional=portfolio.committed_notional,
        committed_open_risk=portfolio.committed_open_risk,
        open_position_count=portfolio.open_position_count,
        realized_pnl_today=portfolio.realized_pnl_today,
        provider_timestamp=balances.as_of,
        portfolio_timestamp=portfolio.observed_at,
        receipt_timestamp=received_at.isoformat(),
        source="SCHWAB_READ_ONLY_BOUND_ACCOUNT",
        portfolio_source=portfolio.source,
        order_transmission=TRANSMISSION_UNAVAILABLE,
    )


def build_account_allocation_decision(
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    policy: AccountAllocationPolicy,
    context: AccountAllocationContext,
    decision_at: datetime,
) -> AccountAllocationDecision:
    return AccountAllocationDecision(
        policy=policy,
        context=context,
        evidence=allocate_account_position(
            trade_plan_id=trade_plan_id,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            policy=policy,
            context=context,
            decision_at=decision_at,
        ),
    )


def account_allocation_decision_from_dict(
    payload: dict[str, Any],
) -> AccountAllocationDecision:
    policy_payload = payload.get("policy")
    context_payload = payload.get("context")
    evidence_payload = payload.get("evidence")
    if not isinstance(policy_payload, dict):
        raise ValueError("Account allocation policy evidence is missing or invalid.")
    if not isinstance(context_payload, dict):
        raise ValueError("Account allocation context evidence is missing or invalid.")
    if not isinstance(evidence_payload, dict):
        raise ValueError("Account allocation result evidence is missing or invalid.")
    normalized_evidence = dict(evidence_payload)
    blockers = normalized_evidence.get("blockers")
    if isinstance(blockers, list):
        normalized_evidence["blockers"] = tuple(str(item) for item in blockers)
    return AccountAllocationDecision(
        policy=AccountAllocationPolicy(**policy_payload),
        context=AccountAllocationContext(**context_payload),
        evidence=AccountAllocationEvidence(**normalized_evidence),
    )


def allocate_account_position(
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    policy: AccountAllocationPolicy,
    context: AccountAllocationContext,
    decision_at: datetime,
) -> AccountAllocationEvidence:
    blockers = policy_findings(policy) + context_findings(context, policy, decision_at=decision_at)
    plan_id = trade_plan_id.strip() if isinstance(trade_plan_id, str) else ""
    if not plan_id:
        blockers.append("ALLOCATION_TRADE_PLAN_ID_MISSING")

    entry = finite_number(entry_price)
    stop = finite_number(stop_price)
    target = finite_number(target_price)
    if entry is None or entry <= 0:
        blockers.append("ALLOCATION_ENTRY_INVALID")
    if stop is None or entry is None or stop <= 0 or stop >= entry:
        blockers.append("ALLOCATION_STOP_INVALID")
    if target is None or entry is None or target <= entry:
        blockers.append("ALLOCATION_TARGET_INVALID")

    risk_per_share = entry - stop if entry is not None and stop is not None and 0 < stop < entry else None
    effective_cash = available_cash(context, policy)
    effective_risk = available_risk(context, policy)
    quantity = 0
    position_notional: float | None = None
    total_risk: float | None = None
    target_reward: float | None = None
    reward_risk_ratio: float | None = None

    if not blockers and entry is not None and target is not None and risk_per_share is not None:
        assert effective_cash is not None
        assert effective_risk is not None
        assert policy.max_position_notional_dollars is not None
        risk_quantity = math.floor(effective_risk / risk_per_share)
        cash_quantity = math.floor(effective_cash / entry)
        notional_quantity = math.floor(policy.max_position_notional_dollars / entry)
        quantity = min(risk_quantity, cash_quantity, notional_quantity)
        if quantity <= 0:
            blockers.append("ALLOCATION_ZERO_WHOLE_SHARES")
            quantity = 0
        else:
            position_notional = round(entry * quantity, 4)
            total_risk = round(risk_per_share * quantity, 4)
            target_reward = round((target - entry) * quantity, 4)
            reward_risk_ratio = round(target_reward / total_risk, 4) if total_risk > 0 else None

    return AccountAllocationEvidence(
        trade_plan_id=plan_id,
        decision_at=decision_at.isoformat(),
        status=ALLOCATION_BLOCKED if blockers else ALLOCATION_AUTHORIZED,
        quantity=quantity,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        risk_per_share=round(risk_per_share, 4) if risk_per_share is not None else None,
        position_notional=position_notional,
        total_risk=total_risk,
        target_reward=target_reward,
        reward_risk_ratio=reward_risk_ratio,
        effective_cash_available=round(effective_cash, 4) if effective_cash is not None else None,
        effective_risk_budget=round(effective_risk, 4) if effective_risk is not None else None,
        policy_fingerprint=policy.fingerprint,
        account_context_fingerprint=context.fingerprint,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def verify_account_allocation(
    evidence: AccountAllocationEvidence,
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    policy: AccountAllocationPolicy,
    context: AccountAllocationContext,
    decision_at: datetime,
) -> tuple[str, ...]:
    expected = allocate_account_position(
        trade_plan_id=trade_plan_id,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        policy=policy,
        context=context,
        decision_at=decision_at,
    )
    if asdict(evidence) != asdict(expected):
        return ("ALLOCATION_EVIDENCE_MISMATCH",)
    if not evidence.authorized:
        return evidence.blockers or ("ALLOCATION_NOT_AUTHORIZED",)
    return ()


def account_allocation_decision_findings(
    decision: AccountAllocationDecision | None,
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    decision_at: datetime,
) -> tuple[str, ...]:
    if decision is None:
        return ("ACCOUNT_ALLOCATION_EVIDENCE_MISSING",)
    if not isinstance(decision, AccountAllocationDecision):
        return ("ACCOUNT_ALLOCATION_EVIDENCE_INVALID",)
    try:
        return verify_account_allocation(
            decision.evidence,
            trade_plan_id=trade_plan_id,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            policy=decision.policy,
            context=decision.context,
            decision_at=decision_at,
        )
    except (AttributeError, OverflowError, TypeError, ValueError):
        return ("ACCOUNT_ALLOCATION_EVIDENCE_INVALID",)


def policy_findings(policy: AccountAllocationPolicy) -> list[str]:
    findings: list[str] = []
    if policy.schema_version != ACCOUNT_ALLOCATION_SCHEMA_VERSION or policy.profile != ACCOUNT_ALLOCATION_PROFILE:
        findings.append("ALLOCATION_POLICY_SCHEMA_UNSUPPORTED")
    if not isinstance(policy.policy_id, str) or not policy.policy_id.strip():
        findings.append("ALLOCATION_POLICY_ID_MISSING")
    for field_name, value in (
        ("FIXED_UNIT_RISK", policy.fixed_unit_risk_dollars),
        ("MAX_POSITION_NOTIONAL", policy.max_position_notional_dollars),
        ("MAX_TOTAL_OPEN_RISK", policy.max_total_open_risk_dollars),
        ("DAILY_LOSS_LIMIT", policy.daily_loss_limit_dollars),
    ):
        if finite_number(value) is None or float(value) <= 0:
            findings.append(f"ALLOCATION_POLICY_{field_name}_MISSING_OR_INVALID")
    reserve = finite_number(policy.minimum_cash_reserve_dollars)
    if reserve is None or reserve < 0:
        findings.append("ALLOCATION_POLICY_CASH_RESERVE_MISSING_OR_INVALID")
    if (
        isinstance(policy.max_open_positions, bool)
        or not isinstance(policy.max_open_positions, int)
        or policy.max_open_positions <= 0
    ):
        findings.append("ALLOCATION_POLICY_MAX_OPEN_POSITIONS_MISSING_OR_INVALID")
    if (
        isinstance(policy.max_balance_age_seconds, bool)
        or not isinstance(policy.max_balance_age_seconds, int)
        or policy.max_balance_age_seconds <= 0
    ):
        findings.append("ALLOCATION_POLICY_BALANCE_AGE_MISSING_OR_INVALID")
    if policy.whole_shares_only is not True:
        findings.append("ALLOCATION_POLICY_FRACTIONAL_SHARES_UNSUPPORTED")
    return findings


def context_findings(
    context: AccountAllocationContext,
    policy: AccountAllocationPolicy,
    *,
    decision_at: datetime,
) -> list[str]:
    findings: list[str] = []
    if (
        isinstance(context.authorized_account_count, bool)
        or context.authorized_account_count != 1
    ):
        findings.append("ALLOCATION_ACCOUNT_COUNT_NOT_ONE")
    if context.account_ending != EXPECTED_ACCOUNT_ENDING:
        findings.append("ALLOCATION_ACCOUNT_ENDING_MISMATCH")
    if context.account_type != EXPECTED_ACCOUNT_TYPE:
        findings.append("ALLOCATION_ACCOUNT_TYPE_INVALID")
    if not isinstance(context.binding_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", context.binding_fingerprint.lower()
    ):
        findings.append("ALLOCATION_BINDING_FINGERPRINT_INVALID")
    if not isinstance(context.source, str) or not context.source.strip():
        findings.append("ALLOCATION_ACCOUNT_SOURCE_MISSING")
    if not isinstance(context.portfolio_source, str) or not context.portfolio_source.strip():
        findings.append("ALLOCATION_PORTFOLIO_SOURCE_MISSING")
    if context.order_transmission != TRANSMISSION_UNAVAILABLE:
        findings.append("ALLOCATION_ORDER_TRANSMISSION_NOT_LOCKED")

    for field_name, value in (
        ("CASH_AVAILABLE", context.cash_available),
        ("BUYING_POWER", context.buying_power),
        ("LIQUIDATION_VALUE", context.liquidation_value),
        ("COMMITTED_NOTIONAL", context.committed_notional),
        ("COMMITTED_OPEN_RISK", context.committed_open_risk),
    ):
        numeric = finite_number(value)
        if numeric is None or numeric < 0:
            findings.append(f"ALLOCATION_{field_name}_INVALID")
    if (
        isinstance(context.open_position_count, bool)
        or not isinstance(context.open_position_count, int)
        or context.open_position_count < 0
    ):
        findings.append("ALLOCATION_OPEN_POSITION_COUNT_INVALID")
    pnl = finite_number(context.realized_pnl_today)
    if pnl is None:
        findings.append("ALLOCATION_REALIZED_PNL_INVALID")

    provider_at = aware_datetime(context.provider_timestamp)
    portfolio_at = aware_datetime(context.portfolio_timestamp)
    received_at = aware_datetime(context.receipt_timestamp)
    if provider_at is None:
        findings.append("ALLOCATION_PROVIDER_TIMESTAMP_INVALID")
    if received_at is None:
        findings.append("ALLOCATION_RECEIPT_TIMESTAMP_INVALID")
    if portfolio_at is None:
        findings.append("ALLOCATION_PORTFOLIO_TIMESTAMP_INVALID")
    decision_is_aware = (
        decision_at.tzinfo is not None and decision_at.utcoffset() is not None
    )
    if not decision_is_aware:
        findings.append("ALLOCATION_DECISION_TIMESTAMP_NAIVE")
    if provider_at is not None and received_at is not None:
        if provider_at > received_at:
            findings.append("ALLOCATION_PROVIDER_TIMESTAMP_AFTER_RECEIPT")
        if decision_is_aware and received_at > decision_at:
            findings.append("ALLOCATION_RECEIPT_TIMESTAMP_AFTER_DECISION")
        if (
            decision_is_aware
            and isinstance(policy.max_balance_age_seconds, int)
            and not isinstance(policy.max_balance_age_seconds, bool)
            and policy.max_balance_age_seconds > 0
        ):
            age_seconds = (decision_at - provider_at).total_seconds()
            if age_seconds < 0 or age_seconds > policy.max_balance_age_seconds:
                findings.append("ALLOCATION_BALANCE_STALE")
    if portfolio_at is not None and received_at is not None:
        if portfolio_at > received_at:
            findings.append("ALLOCATION_PORTFOLIO_TIMESTAMP_AFTER_RECEIPT")
        if decision_is_aware and portfolio_at > decision_at:
            findings.append("ALLOCATION_PORTFOLIO_TIMESTAMP_AFTER_DECISION")
        if (
            decision_is_aware
            and isinstance(policy.max_balance_age_seconds, int)
            and not isinstance(policy.max_balance_age_seconds, bool)
            and policy.max_balance_age_seconds > 0
        ):
            age_seconds = (decision_at - portfolio_at).total_seconds()
            if age_seconds < 0 or age_seconds > policy.max_balance_age_seconds:
                findings.append("ALLOCATION_PORTFOLIO_STATE_STALE")

    if (
        isinstance(context.open_position_count, int)
        and not isinstance(context.open_position_count, bool)
        and isinstance(policy.max_open_positions, int)
        and not isinstance(policy.max_open_positions, bool)
        and context.open_position_count >= policy.max_open_positions
    ):
        findings.append("ALLOCATION_POSITION_LIMIT_REACHED")
    if pnl is not None and finite_number(policy.daily_loss_limit_dollars) is not None:
        if pnl <= -abs(float(policy.daily_loss_limit_dollars)):
            findings.append("ALLOCATION_DAILY_LOSS_LIMIT_REACHED")
    return findings


def available_cash(
    context: AccountAllocationContext,
    policy: AccountAllocationPolicy,
) -> float | None:
    values = (
        finite_number(context.cash_available),
        finite_number(context.buying_power),
        finite_number(context.committed_notional),
        finite_number(policy.minimum_cash_reserve_dollars),
    )
    if any(value is None for value in values):
        return None
    cash, buying_power, committed, reserve = (float(value) for value in values)
    return max(0.0, min(cash, buying_power) - committed - reserve)


def available_risk(
    context: AccountAllocationContext,
    policy: AccountAllocationPolicy,
) -> float | None:
    values = (
        finite_number(policy.fixed_unit_risk_dollars),
        finite_number(policy.max_total_open_risk_dollars),
        finite_number(context.committed_open_risk),
    )
    if any(value is None for value in values):
        return None
    unit_risk, total_limit, committed = (float(value) for value in values)
    return max(0.0, min(unit_risk, total_limit - committed))


def finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def aware_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def payload_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        canonicalize_fingerprint_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonicalize_fingerprint_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "INVALID_NONFINITE"
    if isinstance(value, dict):
        return {
            str(key): canonicalize_fingerprint_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_fingerprint_value(item) for item in value]
    return value
