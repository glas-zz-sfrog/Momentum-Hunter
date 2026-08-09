from __future__ import annotations

"""Offline provider-neutral allocation contracts for future Paper execution."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from enum import Enum
from typing import Any

from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_LIMIT,
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_QUANTITY,
    CAPABILITY_FRACTIONAL_STOP,
    CAPABILITY_FRACTIONAL_STOP_LIMIT,
    CAPABILITY_LIMIT_ORDER,
    CAPABILITY_MARKET_ORDER,
    CAPABILITY_STOP_LIMIT_ORDER,
    CAPABILITY_STOP_ORDER,
    CAPABILITY_WHOLE_QUANTITY,
    BrokerCapabilityRegistry,
)


PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION = 1
PROVIDER_NEUTRAL_ALLOCATION_PROFILE = "provider-neutral-account-allocation-v1"


class QuantityPolicy(str, Enum):
    CAPABILITY_DRIVEN = "CAPABILITY_DRIVEN"
    WHOLE_ONLY = "WHOLE_ONLY"


class QuantityMode(str, Enum):
    FRACTIONAL = "FRACTIONAL"
    WHOLE = "WHOLE"
    UNAVAILABLE = "UNAVAILABLE"


class AllocationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ProviderNeutralAllocationPolicy:
    policy_id: str
    fixed_unit_risk_dollars: Decimal
    max_position_notional_dollars: Decimal
    minimum_cash_reserve_dollars: Decimal
    max_total_open_risk_dollars: Decimal
    daily_loss_limit_dollars: Decimal
    max_open_positions: int
    max_snapshot_age_seconds: int
    quantity_policy: QuantityPolicy = QuantityPolicy.CAPABILITY_DRIVEN
    schema_version: int = PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION
    profile: str = PROVIDER_NEUTRAL_ALLOCATION_PROFILE

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class AccountSnapshot:
    snapshot_id: str
    decision_cycle_id: str
    lane: str
    provider: str
    environment: str
    binding_fingerprint: str
    authorized_account_count: int
    status: str
    cash_available: Decimal
    buying_power: Decimal
    committed_notional: Decimal
    committed_open_risk: Decimal
    open_position_count: int
    realized_pnl_today: Decimal
    provider_timestamp: str
    portfolio_timestamp: str
    receipt_timestamp: str
    source_identity: str
    schema_version: int = PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class AllocationRequest:
    decision_cycle_id: str
    candidate_id: str
    canonical_rank: int
    symbol: str
    trade_plan_id: str
    risk_decision_id: str
    entry_order_type: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    decision_at: str

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class ProviderNeutralAllocationDecision:
    request_fingerprint: str
    policy_fingerprint: str
    account_snapshot_fingerprint: str
    capability_registry_fingerprint: str
    status: AllocationStatus
    quantity_mode: QuantityMode
    quantity_increment: Decimal | None
    ideal_risk_quantity: Decimal | None
    provider_executable_quantity: Decimal
    final_authorized_quantity: Decimal
    risk_per_share: Decimal | None
    effective_cash_available: Decimal | None
    effective_open_risk_available: Decimal | None
    position_notional: Decimal | None
    total_risk: Decimal | None
    target_reward: Decimal | None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION
    profile: str = PROVIDER_NEUTRAL_ALLOCATION_PROFILE

    @property
    def authorized(self) -> bool:
        return (
            self.status is AllocationStatus.AUTHORIZED
            and self.final_authorized_quantity > 0
            and not self.blockers
        )

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "profile": self.profile,
            "requestFingerprint": self.request_fingerprint,
            "policyFingerprint": self.policy_fingerprint,
            "accountSnapshotFingerprint": self.account_snapshot_fingerprint,
            "capabilityRegistryFingerprint": self.capability_registry_fingerprint,
            "status": self.status.value,
            "quantityMode": self.quantity_mode.value,
            "quantityIncrement": decimal_text(self.quantity_increment),
            "idealRiskQuantity": decimal_text(self.ideal_risk_quantity),
            "providerExecutableQuantity": decimal_text(
                self.provider_executable_quantity
            ),
            "finalAuthorizedQuantity": decimal_text(self.final_authorized_quantity),
            "riskPerShare": decimal_text(self.risk_per_share),
            "effectiveCashAvailable": decimal_text(self.effective_cash_available),
            "effectiveOpenRiskAvailable": decimal_text(
                self.effective_open_risk_available
            ),
            "positionNotional": decimal_text(self.position_notional),
            "totalRisk": decimal_text(self.total_risk),
            "targetReward": decimal_text(self.target_reward),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


def allocate_provider_neutral_position(
    *,
    request: AllocationRequest,
    policy: ProviderNeutralAllocationPolicy,
    account: AccountSnapshot,
    capabilities: BrokerCapabilityRegistry,
) -> ProviderNeutralAllocationDecision:
    blockers = _policy_findings(policy)
    decision_at = _aware_datetime(request.decision_at)
    blockers.extend(_request_findings(request, decision_at))
    blockers.extend(
        _account_findings(
            account,
            policy,
            capabilities,
            decision_at=decision_at,
            decision_cycle_id=request.decision_cycle_id,
        )
    )
    quantity_increment, quantity_mode, capability_blockers, warnings = (
        _resolve_quantity_contract(policy, capabilities, request.entry_order_type)
    )
    blockers.extend(capability_blockers)

    entry = _positive_decimal(request.entry_price)
    stop = _positive_decimal(request.stop_price)
    target = _positive_decimal(request.target_price)
    fixed_unit_risk = _positive_decimal(policy.fixed_unit_risk_dollars)
    max_position_notional = _positive_decimal(
        policy.max_position_notional_dollars
    )
    minimum_cash_reserve = _nonnegative_decimal(
        policy.minimum_cash_reserve_dollars
    )
    max_total_open_risk = _positive_decimal(policy.max_total_open_risk_dollars)
    account_cash = _nonnegative_decimal(account.cash_available)
    account_buying_power = _nonnegative_decimal(account.buying_power)
    account_committed_notional = _nonnegative_decimal(account.committed_notional)
    account_committed_risk = _nonnegative_decimal(account.committed_open_risk)
    risk_per_share: Decimal | None = None
    if entry is None:
        blockers.append("ALLOCATION_ENTRY_INVALID")
    if stop is None or entry is None or stop >= entry:
        blockers.append("ALLOCATION_STOP_INVALID")
    if target is None or entry is None or target <= entry:
        blockers.append("ALLOCATION_TARGET_INVALID")
    if entry is not None and stop is not None and stop < entry:
        risk_per_share = entry - stop

    ideal_quantity: Decimal | None = None
    provider_quantity = Decimal("0")
    final_quantity = Decimal("0")
    effective_cash: Decimal | None = None
    effective_open_risk: Decimal | None = None
    if risk_per_share is not None and fixed_unit_risk is not None:
        ideal_quantity = fixed_unit_risk / risk_per_share
    if ideal_quantity is not None and quantity_increment is not None:
        provider_quantity = floor_to_increment(ideal_quantity, quantity_increment)
        if provider_quantity <= 0:
            blockers.append("ALLOCATION_ZERO_PROVIDER_EXECUTABLE_QUANTITY")

    if (
        entry is not None
        and risk_per_share is not None
        and max_position_notional is not None
        and minimum_cash_reserve is not None
        and max_total_open_risk is not None
        and account_cash is not None
        and account_buying_power is not None
        and account_committed_notional is not None
        and account_committed_risk is not None
    ):
        effective_cash = max(
            Decimal("0"),
            min(account_cash, account_buying_power)
            - minimum_cash_reserve
            - account_committed_notional,
        )
        effective_open_risk = max(
            Decimal("0"),
            max_total_open_risk - account_committed_risk,
        )
        if effective_cash <= 0:
            blockers.append("ALLOCATION_INSUFFICIENT_BUYING_POWER")
        if effective_open_risk <= 0:
            blockers.append("ALLOCATION_OPEN_RISK_LIMIT_REACHED")
        if quantity_increment is not None and provider_quantity > 0:
            cash_quantity = floor_to_increment(
                effective_cash / entry, quantity_increment
            )
            notional_quantity = floor_to_increment(
                max_position_notional / entry,
                quantity_increment,
            )
            open_risk_quantity = floor_to_increment(
                effective_open_risk / risk_per_share,
                quantity_increment,
            )
            final_quantity = min(
                provider_quantity,
                cash_quantity,
                notional_quantity,
                open_risk_quantity,
            )
            if final_quantity <= 0:
                blockers.append("ALLOCATION_ZERO_FINAL_AUTHORIZED_QUANTITY")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        final_quantity = Decimal("0")
    position_notional = entry * final_quantity if entry and final_quantity else None
    total_risk = (
        risk_per_share * final_quantity
        if risk_per_share is not None and final_quantity
        else None
    )
    target_reward = (
        (target - entry) * final_quantity
        if target is not None and entry is not None and final_quantity
        else None
    )
    return ProviderNeutralAllocationDecision(
        request_fingerprint=request.fingerprint,
        policy_fingerprint=policy.fingerprint,
        account_snapshot_fingerprint=account.fingerprint,
        capability_registry_fingerprint=capabilities.fingerprint,
        status=(
            AllocationStatus.BLOCKED
            if blockers
            else AllocationStatus.AUTHORIZED
        ),
        quantity_mode=quantity_mode,
        quantity_increment=quantity_increment,
        ideal_risk_quantity=ideal_quantity,
        provider_executable_quantity=provider_quantity,
        final_authorized_quantity=final_quantity,
        risk_per_share=risk_per_share,
        effective_cash_available=effective_cash,
        effective_open_risk_available=effective_open_risk,
        position_notional=position_notional,
        total_risk=total_risk,
        target_reward=target_reward,
        blockers=tuple(blockers),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _resolve_quantity_contract(
    policy: ProviderNeutralAllocationPolicy,
    capabilities: BrokerCapabilityRegistry,
    entry_order_type: str,
) -> tuple[Decimal | None, QuantityMode, list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    order_capability = {
        "market": CAPABILITY_MARKET_ORDER,
        "limit": CAPABILITY_LIMIT_ORDER,
        "stop": CAPABILITY_STOP_ORDER,
        "stop_limit": CAPABILITY_STOP_LIMIT_ORDER,
    }.get(entry_order_type if isinstance(entry_order_type, str) else "")
    fractional_order_capability = {
        "market": CAPABILITY_FRACTIONAL_MARKET,
        "limit": CAPABILITY_FRACTIONAL_LIMIT,
        "stop": CAPABILITY_FRACTIONAL_STOP,
        "stop_limit": CAPABILITY_FRACTIONAL_STOP_LIMIT,
    }.get(entry_order_type if isinstance(entry_order_type, str) else "")
    if order_capability is None:
        blockers.append("ALLOCATION_ENTRY_ORDER_TYPE_UNSUPPORTED")

    whole_proven = capabilities.get(CAPABILITY_WHOLE_QUANTITY).is_proven
    fractional_proven = capabilities.get(CAPABILITY_FRACTIONAL_QUANTITY).is_proven
    precision = capabilities.get(CAPABILITY_FRACTIONAL_PRECISION)
    fractional_increment = (
        _fractional_increment(precision.value) if precision.is_proven else None
    )
    if policy.quantity_policy is QuantityPolicy.WHOLE_ONLY:
        if not whole_proven:
            blockers.append("ALLOCATION_WHOLE_QUANTITY_CAPABILITY_UNPROVEN")
            return None, QuantityMode.UNAVAILABLE, blockers, warnings
        if order_capability is None or not capabilities.get(order_capability).is_proven:
            blockers.append("ALLOCATION_ENTRY_ORDER_CAPABILITY_UNPROVEN")
            return None, QuantityMode.UNAVAILABLE, blockers, warnings
        return Decimal("1"), QuantityMode.WHOLE, blockers, warnings
    fractional_order_proven = (
        fractional_order_capability is not None
        and capabilities.get(fractional_order_capability).is_proven
    )
    if fractional_proven and fractional_increment is not None and fractional_order_proven:
        return fractional_increment, QuantityMode.FRACTIONAL, blockers, warnings
    if whole_proven:
        if order_capability is None or not capabilities.get(order_capability).is_proven:
            blockers.append("ALLOCATION_ENTRY_ORDER_CAPABILITY_UNPROVEN")
            return None, QuantityMode.UNAVAILABLE, blockers, warnings
        warnings.append(
            "ALLOCATION_FRACTIONAL_CAPABILITY_NOT_USED"
            if not fractional_proven or fractional_increment is None
            else "ALLOCATION_FRACTIONAL_ORDER_CAPABILITY_UNPROVEN"
        )
        return Decimal("1"), QuantityMode.WHOLE, blockers, warnings
    if fractional_proven:
        blockers.append(
            "ALLOCATION_FRACTIONAL_PRECISION_UNPROVEN"
            if fractional_increment is None
            else "ALLOCATION_FRACTIONAL_ORDER_CAPABILITY_UNPROVEN"
        )
    else:
        blockers.append("ALLOCATION_QUANTITY_CAPABILITY_UNPROVEN")
    return None, QuantityMode.UNAVAILABLE, blockers, warnings


def _policy_findings(policy: ProviderNeutralAllocationPolicy) -> list[str]:
    findings: list[str] = []
    if (
        policy.schema_version != PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION
        or policy.profile != PROVIDER_NEUTRAL_ALLOCATION_PROFILE
    ):
        findings.append("ALLOCATION_POLICY_SCHEMA_UNSUPPORTED")
    if not _nonempty_text(policy.policy_id):
        findings.append("ALLOCATION_POLICY_ID_MISSING")
    for name, value in (
        ("FIXED_UNIT_RISK", policy.fixed_unit_risk_dollars),
        ("MAX_POSITION_NOTIONAL", policy.max_position_notional_dollars),
        ("MAX_TOTAL_OPEN_RISK", policy.max_total_open_risk_dollars),
        ("DAILY_LOSS_LIMIT", policy.daily_loss_limit_dollars),
    ):
        if _positive_decimal(value) is None:
            findings.append(f"ALLOCATION_POLICY_{name}_INVALID")
    if _nonnegative_decimal(policy.minimum_cash_reserve_dollars) is None:
        findings.append("ALLOCATION_POLICY_CASH_RESERVE_INVALID")
    if (
        not isinstance(policy.max_open_positions, int)
        or isinstance(policy.max_open_positions, bool)
        or policy.max_open_positions <= 0
    ):
        findings.append("ALLOCATION_POLICY_MAX_POSITIONS_INVALID")
    if (
        not isinstance(policy.max_snapshot_age_seconds, int)
        or isinstance(policy.max_snapshot_age_seconds, bool)
        or policy.max_snapshot_age_seconds <= 0
    ):
        findings.append("ALLOCATION_POLICY_SNAPSHOT_AGE_INVALID")
    if not isinstance(policy.quantity_policy, QuantityPolicy):
        findings.append("ALLOCATION_POLICY_QUANTITY_MODE_INVALID")
    return findings


def _request_findings(
    request: AllocationRequest,
    decision_at: datetime | None,
) -> list[str]:
    findings: list[str] = []
    for name, value in (
        ("DECISION_CYCLE_ID", request.decision_cycle_id),
        ("CANDIDATE_ID", request.candidate_id),
        ("SYMBOL", request.symbol),
        ("TRADE_PLAN_ID", request.trade_plan_id),
        ("RISK_DECISION_ID", request.risk_decision_id),
    ):
        if not isinstance(value, str) or not value.strip():
            findings.append(f"ALLOCATION_{name}_MISSING")
    if (
        not isinstance(request.canonical_rank, int)
        or isinstance(request.canonical_rank, bool)
        or request.canonical_rank <= 0
    ):
        findings.append("ALLOCATION_CANONICAL_RANK_INVALID")
    if decision_at is None:
        findings.append("ALLOCATION_DECISION_TIMESTAMP_INVALID")
    return findings


def _account_findings(
    account: AccountSnapshot,
    policy: ProviderNeutralAllocationPolicy,
    capabilities: BrokerCapabilityRegistry,
    *,
    decision_at: datetime | None,
    decision_cycle_id: str,
) -> list[str]:
    findings: list[str] = []
    if account.schema_version != PROVIDER_NEUTRAL_ALLOCATION_SCHEMA_VERSION:
        findings.append("ALLOCATION_ACCOUNT_SCHEMA_UNSUPPORTED")
    if (
        not _nonempty_text(account.snapshot_id)
        or not _nonempty_text(account.decision_cycle_id)
        or not _nonempty_text(account.lane)
    ):
        findings.append("ALLOCATION_ACCOUNT_IDENTITY_MISSING")
    elif account.decision_cycle_id != decision_cycle_id:
        findings.append("ALLOCATION_ACCOUNT_DECISION_CYCLE_MISMATCH")
    if account.provider != capabilities.provider:
        findings.append("ALLOCATION_PROVIDER_MISMATCH")
    if account.environment != capabilities.environment:
        findings.append("ALLOCATION_ENVIRONMENT_MISMATCH")
    if not isinstance(account.binding_fingerprint, str) or not re.fullmatch(
        r"[0-9A-Fa-f]{64}", account.binding_fingerprint
    ):
        findings.append("ALLOCATION_BINDING_FINGERPRINT_INVALID")
    if (
        not isinstance(account.authorized_account_count, int)
        or isinstance(account.authorized_account_count, bool)
        or account.authorized_account_count != 1
    ):
        findings.append("ALLOCATION_ACCOUNT_COUNT_NOT_ONE")
    if account.status != "ACTIVE":
        findings.append("ALLOCATION_ACCOUNT_NOT_ACTIVE")
    if not _nonempty_text(account.source_identity):
        findings.append("ALLOCATION_ACCOUNT_SOURCE_MISSING")
    for name, value in (
        ("CASH", account.cash_available),
        ("BUYING_POWER", account.buying_power),
        ("COMMITTED_NOTIONAL", account.committed_notional),
        ("COMMITTED_OPEN_RISK", account.committed_open_risk),
    ):
        if _nonnegative_decimal(value) is None:
            findings.append(f"ALLOCATION_ACCOUNT_{name}_INVALID")
    valid_open_position_count = (
        isinstance(account.open_position_count, int)
        and not isinstance(account.open_position_count, bool)
        and account.open_position_count >= 0
    )
    if not valid_open_position_count:
        findings.append("ALLOCATION_OPEN_POSITION_COUNT_INVALID")
    realized_pnl = _finite_decimal(account.realized_pnl_today)
    if realized_pnl is None:
        findings.append("ALLOCATION_REALIZED_PNL_INVALID")

    provider_at = _aware_datetime(account.provider_timestamp)
    portfolio_at = _aware_datetime(account.portfolio_timestamp)
    receipt_at = _aware_datetime(account.receipt_timestamp)
    if provider_at is None or portfolio_at is None or receipt_at is None:
        findings.append("ALLOCATION_ACCOUNT_TIMESTAMP_INVALID")
    elif decision_at is not None:
        if provider_at > receipt_at or portfolio_at > receipt_at or receipt_at > decision_at:
            findings.append("ALLOCATION_ACCOUNT_TIMESTAMP_ORDER_INVALID")
        max_age = (
            policy.max_snapshot_age_seconds
            if isinstance(policy.max_snapshot_age_seconds, int)
            and not isinstance(policy.max_snapshot_age_seconds, bool)
            and policy.max_snapshot_age_seconds > 0
            else None
        )
        if max_age is not None and (
            (decision_at - provider_at).total_seconds() > max_age
            or (decision_at - portfolio_at).total_seconds() > max_age
        ):
            findings.append("ALLOCATION_ACCOUNT_SNAPSHOT_STALE")
    valid_max_positions = (
        isinstance(policy.max_open_positions, int)
        and not isinstance(policy.max_open_positions, bool)
        and policy.max_open_positions > 0
    )
    if (
        valid_open_position_count
        and valid_max_positions
        and account.open_position_count >= policy.max_open_positions
    ):
        findings.append("ALLOCATION_POSITION_LIMIT_REACHED")
    committed_risk = _nonnegative_decimal(account.committed_open_risk)
    max_open_risk = _positive_decimal(policy.max_total_open_risk_dollars)
    if (
        committed_risk is not None
        and max_open_risk is not None
        and committed_risk >= max_open_risk
    ):
        findings.append("ALLOCATION_OPEN_RISK_LIMIT_REACHED")
    daily_loss_limit = _positive_decimal(policy.daily_loss_limit_dollars)
    if (
        realized_pnl is not None
        and daily_loss_limit is not None
        and realized_pnl <= -daily_loss_limit
    ):
        findings.append("ALLOCATION_DAILY_LOSS_LIMIT_REACHED")
    return findings


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if value < 0 or increment <= 0:
        raise ValueError("Quantity and increment must be nonnegative and positive.")
    units = (value / increment).to_integral_value(rounding=ROUND_FLOOR)
    return units * increment


def _fractional_increment(value: str) -> Decimal | None:
    if not re.fullmatch(r"0\.\d+", value.strip()):
        return None
    increment = _positive_decimal(value)
    if increment is None or increment >= 1:
        return None
    reciprocal = Decimal("1") / increment
    if reciprocal != reciprocal.to_integral_value():
        return None
    return increment


def _aware_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _finite_decimal(value)
    return parsed if parsed is not None and parsed > 0 else None


def _nonnegative_decimal(value: object) -> Decimal | None:
    parsed = _finite_decimal(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def evidence_fingerprint(value: object) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value
