from __future__ import annotations

"""Nontransmitting order identity and broker-truth reconciliation."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from math import isclose, isfinite
import re
from typing import Final, Iterable

from momentum_hunter.schwab_readonly import SchwabOrder


CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_ORDER_RECONCILIATION_V1"
)
CURRENT_ORDER_SOURCE: Final = "SCHWAB_READ_ONLY_ORDER_V1"
SUPPORTED_SIDES: Final = frozenset({"BUY", "SELL"})
SUPPORTED_ORDER_TYPES: Final = frozenset({"MARKET", "LIMIT"})
SUPPORTED_STATUSES: Final = frozenset(
    {
        "PENDING_ACK",
        "WORKING",
        "PARTIALLY_FILLED",
        "CANCEL_PENDING",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    }
)
TERMINAL_STATUSES: Final = frozenset(
    {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
)
STATUS_ALIASES: Final = {
    "PENDING": "PENDING_ACK",
    "AWAITING_ACKNOWLEDGEMENT": "PENDING_ACK",
    "AWAITING_ACKNOWLEDGMENT": "PENDING_ACK",
    "OPEN": "WORKING",
    "PARTIAL": "PARTIALLY_FILLED",
    "PARTIALLY FILLED": "PARTIALLY_FILLED",
    "PENDING_CANCEL": "CANCEL_PENDING",
    "CANCEL PENDING": "CANCEL_PENDING",
    "CANCELLED": "CANCELED",
}
ALLOWED_TRANSITIONS: Final = {
    "PENDING_ACK": frozenset(
        {
            "PENDING_ACK",
            "WORKING",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "FILLED",
            "CANCELED",
            "REJECTED",
        }
    ),
    "WORKING": frozenset(
        {
            "WORKING",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "FILLED",
            "CANCELED",
        }
    ),
    "PARTIALLY_FILLED": frozenset(
        {
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "FILLED",
            "CANCELED",
        }
    ),
    "CANCEL_PENDING": frozenset(
        {
            "CANCEL_PENDING",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELED",
        }
    ),
    "FILLED": frozenset({"FILLED"}),
    "CANCELED": frozenset({"CANCELED"}),
    "REJECTED": frozenset({"REJECTED"}),
    "EXPIRED": frozenset({"EXPIRED"}),
}
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_QUANTITY_TOLERANCE = 1e-9


class CanaryOrderReconciliationError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class CanaryOrderIntent:
    sequence_id: str
    account_binding_commitment: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    created_at: str
    limit_price: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sequence_id",
            _normalize_identifier(self.sequence_id, field="sequence ID"),
        )
        object.__setattr__(
            self,
            "account_binding_commitment",
            _normalize_commitment(self.account_binding_commitment),
        )
        symbol = str(self.symbol).strip().upper()
        if not symbol or len(symbol) > 12 or not symbol.isascii():
            raise CanaryOrderReconciliationError(
                "Canary order symbol must be non-empty ASCII and at most 12 characters."
            )
        object.__setattr__(self, "symbol", symbol)
        side = str(self.side).strip().upper()
        if side not in SUPPORTED_SIDES:
            raise CanaryOrderReconciliationError(
                "Canary order side must be BUY or SELL."
            )
        object.__setattr__(self, "side", side)
        order_type = str(self.order_type).strip().upper()
        if order_type not in SUPPORTED_ORDER_TYPES:
            raise CanaryOrderReconciliationError(
                "Canary order type must be MARKET or LIMIT."
            )
        object.__setattr__(self, "order_type", order_type)
        if not _is_positive_number(self.quantity):
            raise CanaryOrderReconciliationError(
                "Canary order quantity must be finite and greater than zero."
            )
        if order_type == "LIMIT":
            if not _is_positive_number(self.limit_price):
                raise CanaryOrderReconciliationError(
                    "A LIMIT canary order requires a positive finite limit price."
                )
        elif self.limit_price is not None:
            raise CanaryOrderReconciliationError(
                "A MARKET canary order cannot contain a limit price."
            )
        _require_timestamp(self.created_at, field="intent creation")

    def __repr__(self) -> str:
        return (
            "CanaryOrderIntent("
            f"sequence_id={self.sequence_id!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"symbol={self.symbol!r}, side={self.side!r}, "
            f"quantity={self.quantity!r}, order_type={self.order_type!r}, "
            f"created_at={self.created_at!r}, limit_price={self.limit_price!r})"
        )

    @property
    def command_id(self) -> str:
        canonical = {
            "accountBindingCommitment": self.account_binding_commitment,
            "createdAt": _canonical_timestamp(self.created_at),
            "limitPrice": self.limit_price,
            "orderType": self.order_type,
            "quantity": self.quantity,
            "schemaVersion": CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION,
            "sequenceId": self.sequence_id,
            "side": self.side,
            "symbol": self.symbol,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return f"canary-order-{digest}"


@dataclass(frozen=True, repr=False)
class CanarySubmissionAttempt:
    command_id: str
    sequence_id: str
    account_binding_commitment: str
    attempted_at: str

    def __repr__(self) -> str:
        return (
            "CanarySubmissionAttempt("
            f"command_id={self.command_id!r}, "
            f"sequence_id={self.sequence_id!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"attempted_at={self.attempted_at!r})"
        )


@dataclass(frozen=True, repr=False)
class CanaryBrokerOrderObservation:
    provider_order_id: str
    client_command_id: str | None
    source: str
    account_binding_commitment: str
    symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float | None
    remaining_quantity: float | None
    average_fill_price: float | None
    order_type: str
    status: str
    entered_at: str
    updated_at: str | None
    observed_at: str

    def __repr__(self) -> str:
        return (
            "CanaryBrokerOrderObservation("
            f"provider_order_id={self.provider_order_id!r}, "
            f"client_command_id={self.client_command_id!r}, "
            f"source={self.source!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"symbol={self.symbol!r}, side={self.side!r}, "
            f"requested_quantity={self.requested_quantity!r}, "
            f"filled_quantity={self.filled_quantity!r}, "
            f"remaining_quantity={self.remaining_quantity!r}, "
            f"status={self.status!r}, observed_at={self.observed_at!r})"
        )


@dataclass(frozen=True)
class CanaryOrderReconciliationPolicy:
    expected_source: str
    max_observation_age_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expected_source",
            _normalize_identifier(self.expected_source, field="evidence source"),
        )
        if not _is_positive_number(self.max_observation_age_seconds):
            raise CanaryOrderReconciliationError(
                "Maximum order-observation age must be finite and greater than zero."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryOrderReconciliationError(
                "Maximum future clock skew must be finite and non-negative."
            )


@dataclass(frozen=True)
class CanaryOrderFinding:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CanaryOrderReconciliationResult:
    status: str
    conclusion: str
    command_id: str
    sequence_id: str
    evaluated_at: str
    attempt_recorded: bool
    exact_match_count: int
    provider_order_id: str | None
    broker_status: str | None
    findings: tuple[CanaryOrderFinding, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "commandId": self.command_id,
            "sequenceId": self.sequence_id,
            "evaluatedAt": self.evaluated_at,
            "attemptRecorded": self.attempt_recorded,
            "exactMatchCount": self.exact_match_count,
            "providerOrderId": self.provider_order_id,
            "brokerStatus": self.broker_status,
            "findings": [finding.to_dict() for finding in self.findings],
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def create_account_binding_commitment(*, account_hash: str, salt: str) -> str:
    clean_hash = str(account_hash).strip()
    clean_salt = str(salt).strip()
    if not clean_hash or not clean_salt:
        raise CanaryOrderReconciliationError(
            "Account hash and non-empty salt are required for a binding commitment."
        )
    return hashlib.sha256(
        (
            f"{CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION}\0"
            f"{clean_salt}\0{clean_hash}"
        ).encode("utf-8")
    ).hexdigest()


def map_current_schwab_order(
    order: SchwabOrder,
    *,
    expected_account_hash: str,
    account_binding_salt: str,
    observed_at: str,
) -> CanaryBrokerOrderObservation:
    """Map today's read model without pretending unavailable evidence exists."""

    if order.account_hash != expected_account_hash:
        raise CanaryOrderReconciliationError(
            "The Schwab order belongs to a different account identity."
        )
    return CanaryBrokerOrderObservation(
        provider_order_id=order.order_id,
        client_command_id=None,
        source=CURRENT_ORDER_SOURCE,
        account_binding_commitment=create_account_binding_commitment(
            account_hash=expected_account_hash,
            salt=account_binding_salt,
        ),
        symbol=order.symbol,
        side=order.side,
        requested_quantity=order.quantity,
        filled_quantity=None,
        remaining_quantity=None,
        average_fill_price=None,
        order_type=order.order_type,
        status=order.status,
        entered_at=order.entered_at,
        updated_at=None,
        observed_at=observed_at,
    )


def reconcile_canary_order(
    *,
    intent: CanaryOrderIntent,
    submission_attempt: CanarySubmissionAttempt | None,
    observations: Iterable[CanaryBrokerOrderObservation],
    evaluated_at: datetime,
    policy: CanaryOrderReconciliationPolicy,
    previous_observation: CanaryBrokerOrderObservation | None = None,
) -> CanaryOrderReconciliationResult:
    evaluation_time = _require_aware_datetime(
        evaluated_at,
        field="evaluation",
    )
    findings: list[CanaryOrderFinding] = []
    intent_time = _parse_timestamp(
        intent.created_at,
        field="intent creation",
        code_prefix="INTENT_TIME",
        findings=findings,
    )
    attempt_time = _validate_attempt(
        intent=intent,
        submission_attempt=submission_attempt,
        intent_time=intent_time,
        evaluated_at=evaluation_time,
        policy=policy,
        findings=findings,
    )
    observed_items = tuple(observations)
    matching = [
        item for item in observed_items if item.client_command_id == intent.command_id
    ]
    command_conflicts = [
        item
        for item in observed_items
        if item.client_command_id == intent.command_id
        and not _identity_matches(intent, item)
    ]
    for item in observed_items:
        _validate_observation(
            item,
            intent=intent,
            evaluation_time=evaluation_time,
            policy=policy,
            submission_time=attempt_time,
            findings=findings,
        )
    if command_conflicts:
        findings.append(
            CanaryOrderFinding(
                code="COMMAND_IDENTITY_CONFLICT",
                message=(
                    "A broker order reused the command ID with different order identity."
                ),
            )
        )
    exact_matches = [
        item for item in matching if _identity_matches(intent, item)
    ]
    if len(exact_matches) > 1:
        findings.append(
            CanaryOrderFinding(
                code="DUPLICATE_EXACT_ORDERS",
                message=(
                    "Multiple broker orders match the one deterministic command ID."
                ),
            )
        )
    current = exact_matches[0] if len(exact_matches) == 1 else None
    if current is not None and previous_observation is not None:
        _validate_observation(
            previous_observation,
            intent=intent,
            evaluation_time=evaluation_time,
            policy=policy,
            submission_time=attempt_time,
            findings=findings,
        )
        _validate_lifecycle(
            intent=intent,
            previous=previous_observation,
            current=current,
            policy=policy,
            findings=findings,
        )
    if submission_attempt is None and exact_matches:
        findings.append(
            CanaryOrderFinding(
                code="ORDER_WITHOUT_SUBMISSION_ATTEMPT",
                message=(
                    "Broker order evidence exists without a matching local submission attempt."
                ),
            )
        )
    unique_findings = _deduplicate_findings(findings)
    conclusion = _classify_conclusion(
        submission_attempt=submission_attempt,
        observations=observed_items,
        exact_matches=exact_matches,
        findings=unique_findings,
    )
    passed = (
        conclusion == "RESUME_EXISTING_ORDER"
        and not unique_findings
        and current is not None
    )
    return CanaryOrderReconciliationResult(
        status="PASS" if passed else "BLOCK",
        conclusion=conclusion,
        command_id=intent.command_id,
        sequence_id=intent.sequence_id,
        evaluated_at=evaluation_time.isoformat(),
        attempt_recorded=submission_attempt is not None,
        exact_match_count=len(exact_matches),
        provider_order_id=current.provider_order_id if current else None,
        broker_status=_normalize_status(current.status) if current else None,
        findings=unique_findings,
    )


def _validate_attempt(
    *,
    intent: CanaryOrderIntent,
    submission_attempt: CanarySubmissionAttempt | None,
    intent_time: datetime | None,
    evaluated_at: datetime,
    policy: CanaryOrderReconciliationPolicy,
    findings: list[CanaryOrderFinding],
) -> datetime | None:
    if submission_attempt is None:
        return None
    if submission_attempt.command_id != intent.command_id:
        findings.append(
            CanaryOrderFinding(
                code="ATTEMPT_COMMAND_MISMATCH",
                message="Submission attempt command ID does not match the intent.",
            )
        )
    if submission_attempt.sequence_id != intent.sequence_id:
        findings.append(
            CanaryOrderFinding(
                code="ATTEMPT_SEQUENCE_MISMATCH",
                message="Submission attempt sequence ID does not match the intent.",
            )
        )
    if (
        submission_attempt.account_binding_commitment
        != intent.account_binding_commitment
    ):
        findings.append(
            CanaryOrderFinding(
                code="ATTEMPT_ACCOUNT_MISMATCH",
                message="Submission attempt is bound to a different account identity.",
            )
        )
    attempted_at = _parse_timestamp(
        submission_attempt.attempted_at,
        field="submission attempt",
        code_prefix="ATTEMPT_TIME",
        findings=findings,
    )
    if intent_time is not None and attempted_at is not None:
        if (
            intent_time - attempted_at
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ATTEMPT_BEFORE_INTENT",
                    message="Submission attempt predates the canary order intent.",
                )
            )
    if attempted_at is not None:
        _check_not_future(
            attempted_at,
            evaluated_at=evaluated_at,
            max_future_skew=policy.max_future_skew_seconds,
            code="ATTEMPT_FROM_FUTURE",
            label="Submission attempt",
            findings=findings,
        )
    return attempted_at


def _validate_observation(
    observation: CanaryBrokerOrderObservation,
    *,
    intent: CanaryOrderIntent,
    evaluation_time: datetime,
    policy: CanaryOrderReconciliationPolicy,
    submission_time: datetime | None,
    findings: list[CanaryOrderFinding],
) -> None:
    if not str(observation.provider_order_id).strip():
        findings.append(
            CanaryOrderFinding(
                code="PROVIDER_ORDER_ID_MISSING",
                message="Broker order evidence is missing its provider order ID.",
            )
        )
    if observation.client_command_id is None:
        findings.append(
            CanaryOrderFinding(
                code="CLIENT_COMMAND_ID_UNAVAILABLE",
                message=(
                    "Broker order evidence does not expose the deterministic client command ID."
                ),
            )
        )
    elif not str(observation.client_command_id).strip():
        findings.append(
            CanaryOrderFinding(
                code="CLIENT_COMMAND_ID_INVALID",
                message="Broker order evidence contains an empty client command ID.",
            )
        )
    if observation.source != policy.expected_source:
        findings.append(
            CanaryOrderFinding(
                code="EVIDENCE_SOURCE_MISMATCH",
                message="Broker order evidence did not come from the required source.",
            )
        )
    if (
        observation.account_binding_commitment
        != intent.account_binding_commitment
    ):
        findings.append(
            CanaryOrderFinding(
                code="ORDER_ACCOUNT_MISMATCH",
                message="Broker order evidence belongs to a different account identity.",
            )
        )
    status = _normalize_status(observation.status)
    if status not in SUPPORTED_STATUSES:
        findings.append(
            CanaryOrderFinding(
                code="ORDER_STATUS_UNSUPPORTED",
                message="Broker order evidence contains an unsupported status.",
            )
        )
    _validate_quantities(observation, status=status, findings=findings)
    entered_at = _parse_timestamp(
        observation.entered_at,
        field="order entry",
        code_prefix="ORDER_ENTERED_TIME",
        findings=findings,
    )
    updated_at = None
    if observation.updated_at is None:
        findings.append(
            CanaryOrderFinding(
                code="ORDER_UPDATED_TIME_UNAVAILABLE",
                message="Broker order evidence does not expose an update timestamp.",
            )
        )
    else:
        updated_at = _parse_timestamp(
            observation.updated_at,
            field="order update",
            code_prefix="ORDER_UPDATED_TIME",
            findings=findings,
        )
    observed_at = _parse_timestamp(
        observation.observed_at,
        field="order observation",
        code_prefix="ORDER_OBSERVED_TIME",
        findings=findings,
    )
    if entered_at is not None and updated_at is not None:
        if (
            entered_at - updated_at
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ORDER_UPDATE_BEFORE_ENTRY",
                    message="Broker order update predates order entry.",
                )
            )
    if updated_at is not None and observed_at is not None:
        if (
            updated_at - observed_at
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ORDER_UPDATE_AFTER_OBSERVATION",
                    message="Broker order update is later than its observation.",
                )
            )
    if submission_time is not None and entered_at is not None:
        if (
            submission_time - entered_at
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ORDER_ENTERED_BEFORE_ATTEMPT",
                    message="Broker order entry predates the submission attempt.",
                )
            )
    if observed_at is not None:
        _check_age(
            observed_at,
            evaluated_at=evaluation_time,
            max_age=policy.max_observation_age_seconds,
            max_future_skew=policy.max_future_skew_seconds,
            findings=findings,
        )


def _validate_quantities(
    observation: CanaryBrokerOrderObservation,
    *,
    status: str,
    findings: list[CanaryOrderFinding],
) -> None:
    requested = observation.requested_quantity
    filled = observation.filled_quantity
    remaining = observation.remaining_quantity
    if not _is_positive_number(requested):
        findings.append(
            CanaryOrderFinding(
                code="REQUESTED_QUANTITY_INVALID",
                message="Requested order quantity must be finite and positive.",
            )
        )
    if filled is None:
        findings.append(
            CanaryOrderFinding(
                code="FILLED_QUANTITY_UNAVAILABLE",
                message="Broker order evidence does not expose filled quantity.",
            )
        )
    elif not _is_nonnegative_number(filled):
        findings.append(
            CanaryOrderFinding(
                code="FILLED_QUANTITY_INVALID",
                message="Filled quantity must be finite and non-negative.",
            )
        )
    if remaining is None:
        findings.append(
            CanaryOrderFinding(
                code="REMAINING_QUANTITY_UNAVAILABLE",
                message="Broker order evidence does not expose remaining quantity.",
            )
        )
    elif not _is_nonnegative_number(remaining):
        findings.append(
            CanaryOrderFinding(
                code="REMAINING_QUANTITY_INVALID",
                message="Remaining quantity must be finite and non-negative.",
            )
        )
    valid_quantities = (
        _is_positive_number(requested)
        and _is_nonnegative_number(filled)
        and _is_nonnegative_number(remaining)
    )
    if valid_quantities and not isclose(
        float(filled) + float(remaining),
        float(requested),
        rel_tol=0.0,
        abs_tol=_QUANTITY_TOLERANCE,
    ):
        findings.append(
            CanaryOrderFinding(
                code="ORDER_QUANTITY_MISMATCH",
                message=(
                    "Filled plus remaining quantity does not equal requested quantity."
                ),
            )
        )
    average = observation.average_fill_price
    if _is_nonnegative_number(filled) and float(filled) > 0:
        if not _is_positive_number(average):
            findings.append(
                CanaryOrderFinding(
                    code="AVERAGE_FILL_PRICE_MISSING",
                    message="A filled quantity requires a positive average fill price.",
                )
            )
    elif average is not None:
        findings.append(
            CanaryOrderFinding(
                code="AVERAGE_FILL_WITHOUT_FILL",
                message="Average fill price exists while filled quantity is zero.",
            )
        )
    if not valid_quantities or status not in SUPPORTED_STATUSES:
        return
    if status == "FILLED" and (
        not isclose(float(filled), float(requested))
        or not isclose(float(remaining), 0.0, abs_tol=_QUANTITY_TOLERANCE)
    ):
        findings.append(
            CanaryOrderFinding(
                code="FILLED_STATUS_QUANTITY_CONFLICT",
                message="FILLED status requires the entire requested quantity filled.",
            )
        )
    if status == "PARTIALLY_FILLED" and not (
        0 < float(filled) < float(requested) and float(remaining) > 0
    ):
        findings.append(
            CanaryOrderFinding(
                code="PARTIAL_STATUS_QUANTITY_CONFLICT",
                message=(
                    "PARTIALLY_FILLED status requires both filled and remaining quantity."
                ),
            )
        )
    if status in {"PENDING_ACK", "WORKING", "REJECTED"} and float(filled) != 0:
        findings.append(
            CanaryOrderFinding(
                code="UNFILLED_STATUS_QUANTITY_CONFLICT",
                message=f"{status} status cannot contain filled quantity.",
            )
        )
    if status == "REJECTED" and not isclose(
        float(remaining),
        float(requested),
        abs_tol=_QUANTITY_TOLERANCE,
    ):
        findings.append(
            CanaryOrderFinding(
                code="REJECTED_STATUS_QUANTITY_CONFLICT",
                message="REJECTED status requires the full quantity to remain unfilled.",
            )
        )


def _validate_lifecycle(
    *,
    intent: CanaryOrderIntent,
    previous: CanaryBrokerOrderObservation,
    current: CanaryBrokerOrderObservation,
    policy: CanaryOrderReconciliationPolicy,
    findings: list[CanaryOrderFinding],
) -> None:
    if (
        previous.client_command_id != intent.command_id
        or not _identity_matches(intent, previous)
    ):
        findings.append(
            CanaryOrderFinding(
                code="PREVIOUS_ORDER_IDENTITY_MISMATCH",
                message="Previous broker evidence does not match the canary intent.",
            )
        )
        return
    if previous.provider_order_id != current.provider_order_id:
        findings.append(
            CanaryOrderFinding(
                code="PROVIDER_ORDER_ID_CHANGED",
                message="Provider order ID changed for one deterministic command.",
            )
        )
    previous_status = _normalize_status(previous.status)
    current_status = _normalize_status(current.status)
    if (
        previous_status not in SUPPORTED_STATUSES
        or current_status not in SUPPORTED_STATUSES
        or current_status not in ALLOWED_TRANSITIONS[previous_status]
    ):
        findings.append(
            CanaryOrderFinding(
                code="ORDER_LIFECYCLE_REVERSED",
                message=(
                    "Broker order status moved through an unsupported or backward transition."
                ),
            )
        )
    if previous_status in TERMINAL_STATUSES and not _terminal_economics_match(
        previous,
        current,
    ):
        findings.append(
            CanaryOrderFinding(
                code="TERMINAL_ORDER_CHANGED",
                message="A terminal broker order changed after finalization.",
            )
        )
    if _is_nonnegative_number(previous.filled_quantity) and _is_nonnegative_number(
        current.filled_quantity
    ):
        if (
            float(previous.filled_quantity) - float(current.filled_quantity)
            > _QUANTITY_TOLERANCE
        ):
            findings.append(
                CanaryOrderFinding(
                    code="FILLED_QUANTITY_DECREASED",
                    message="Cumulative filled quantity decreased between observations.",
                )
            )
    if _is_nonnegative_number(
        previous.remaining_quantity
    ) and _is_nonnegative_number(current.remaining_quantity):
        if (
            float(current.remaining_quantity) - float(previous.remaining_quantity)
            > _QUANTITY_TOLERANCE
        ):
            findings.append(
                CanaryOrderFinding(
                    code="REMAINING_QUANTITY_INCREASED",
                    message="Remaining quantity increased between observations.",
                )
            )
    previous_updated = _optional_timestamp(previous.updated_at)
    current_updated = _optional_timestamp(current.updated_at)
    if previous_updated is not None and current_updated is not None:
        if (
            previous_updated - current_updated
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ORDER_UPDATE_CLOCK_REVERSED",
                    message="Broker order update timestamp moved backward.",
                )
            )
    previous_observed = _optional_timestamp(previous.observed_at)
    current_observed = _optional_timestamp(current.observed_at)
    if previous_observed is not None and current_observed is not None:
        if (
            previous_observed - current_observed
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryOrderFinding(
                    code="ORDER_OBSERVATION_CLOCK_REVERSED",
                    message="Broker order observation timestamp moved backward.",
                )
            )


def _identity_matches(
    intent: CanaryOrderIntent,
    observation: CanaryBrokerOrderObservation,
) -> bool:
    return (
        observation.account_binding_commitment
        == intent.account_binding_commitment
        and str(observation.symbol).strip().upper() == intent.symbol
        and str(observation.side).strip().upper() == intent.side
        and _numbers_equal(observation.requested_quantity, intent.quantity)
        and str(observation.order_type).strip().upper() == intent.order_type
    )


def _classify_conclusion(
    *,
    submission_attempt: CanarySubmissionAttempt | None,
    observations: tuple[CanaryBrokerOrderObservation, ...],
    exact_matches: list[CanaryBrokerOrderObservation],
    findings: tuple[CanaryOrderFinding, ...],
) -> str:
    codes = {finding.code for finding in findings}
    incomplete_codes = {
        "CLIENT_COMMAND_ID_UNAVAILABLE",
        "FILLED_QUANTITY_UNAVAILABLE",
        "REMAINING_QUANTITY_UNAVAILABLE",
        "ORDER_UPDATED_TIME_UNAVAILABLE",
    }
    if codes & incomplete_codes:
        return "BROKER_EVIDENCE_INCOMPLETE"
    if "DUPLICATE_EXACT_ORDERS" in codes or len(exact_matches) > 1:
        return "DUPLICATE_ORDER_LOCKOUT"
    if submission_attempt is None:
        if exact_matches:
            return "UNEXPECTED_ORDER_WITHOUT_ATTEMPT"
        return "NO_PRIOR_SUBMISSION_EVIDENCE"
    if not exact_matches:
        if codes:
            return "BROKER_EVIDENCE_INVALID"
        return "AMBIGUOUS_SUBMISSION_DO_NOT_RETRY"
    if codes:
        return "BROKER_EVIDENCE_INVALID"
    return "RESUME_EXISTING_ORDER"


def _normalize_status(value: str) -> str:
    normalized = str(value).strip().upper().replace("-", "_")
    return STATUS_ALIASES.get(normalized, normalized)


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = str(value).strip()
    if not _SIMPLE_IDENTIFIER.fullmatch(normalized):
        raise CanaryOrderReconciliationError(
            f"{field.capitalize()} must be a simple ASCII identifier."
        )
    return normalized


def _normalize_commitment(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HEX_SHA256.fullmatch(normalized):
        raise CanaryOrderReconciliationError(
            "Account binding commitment must be a lowercase SHA-256 digest."
        )
    return normalized


def _commitment_tag(value: str) -> str:
    clean = str(value).strip()
    return f"{clean[:12]}..." if clean else "[missing]"


def _canonical_timestamp(value: str) -> str:
    return _require_timestamp(value, field="timestamp").isoformat()


def _require_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryOrderReconciliationError(
            f"{field.capitalize()} timestamp is not valid ISO 8601."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryOrderReconciliationError(
            f"{field.capitalize()} timestamp must include a UTC offset."
        )
    return value


def _parse_timestamp(
    value: str,
    *,
    field: str,
    code_prefix: str,
    findings: list[CanaryOrderFinding],
) -> datetime | None:
    try:
        return _require_timestamp(value, field=field)
    except CanaryOrderReconciliationError as exc:
        code = (
            f"{code_prefix}_NAIVE"
            if "UTC offset" in str(exc)
            else f"{code_prefix}_INVALID"
        )
        findings.append(CanaryOrderFinding(code=code, message=str(exc)))
        return None


def _optional_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _require_timestamp(value, field="optional")
    except CanaryOrderReconciliationError:
        return None


def _check_not_future(
    value: datetime,
    *,
    evaluated_at: datetime,
    max_future_skew: float,
    code: str,
    label: str,
    findings: list[CanaryOrderFinding],
) -> None:
    if (value - evaluated_at).total_seconds() > max_future_skew:
        findings.append(
            CanaryOrderFinding(
                code=code,
                message=f"{label} is later than the permitted clock skew.",
            )
        )


def _check_age(
    value: datetime,
    *,
    evaluated_at: datetime,
    max_age: float,
    max_future_skew: float,
    findings: list[CanaryOrderFinding],
) -> None:
    age = (evaluated_at - value).total_seconds()
    if age < -max_future_skew:
        findings.append(
            CanaryOrderFinding(
                code="ORDER_OBSERVATION_FROM_FUTURE",
                message="Broker order observation is later than permitted clock skew.",
            )
        )
    elif age > max_age:
        findings.append(
            CanaryOrderFinding(
                code="ORDER_OBSERVATION_STALE",
                message="Broker order observation is older than the safety window.",
            )
        )


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _is_positive_number(value: object) -> bool:
    return _is_finite_number(value) and float(value) > 0


def _is_nonnegative_number(value: object) -> bool:
    return _is_finite_number(value) and float(value) >= 0


def _numbers_equal(left: object, right: object) -> bool:
    return (
        _is_finite_number(left)
        and _is_finite_number(right)
        and isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=_QUANTITY_TOLERANCE,
        )
    )


def _optional_numbers_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return _numbers_equal(left, right)


def _terminal_economics_match(
    previous: CanaryBrokerOrderObservation,
    current: CanaryBrokerOrderObservation,
) -> bool:
    return (
        _normalize_status(previous.status) == _normalize_status(current.status)
        and _numbers_equal(
            previous.requested_quantity,
            current.requested_quantity,
        )
        and _optional_numbers_equal(
            previous.filled_quantity,
            current.filled_quantity,
        )
        and _optional_numbers_equal(
            previous.remaining_quantity,
            current.remaining_quantity,
        )
        and _optional_numbers_equal(
            previous.average_fill_price,
            current.average_fill_price,
        )
    )


def _deduplicate_findings(
    findings: list[CanaryOrderFinding],
) -> tuple[CanaryOrderFinding, ...]:
    unique: list[CanaryOrderFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            unique.append(finding)
            seen.add(key)
    return tuple(unique)
