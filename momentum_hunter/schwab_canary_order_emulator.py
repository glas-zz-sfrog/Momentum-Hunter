from __future__ import annotations

"""Deterministic, nonnetwork order-contract scenarios for canary testing."""

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from math import isclose, isfinite
from typing import Final, Mapping

from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryBrokerOrderObservation,
    CanaryOrderIntent,
    CanarySubmissionAttempt,
)


SYNTHETIC_ORDER_CONTRACT_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_SYNTHETIC_ORDER_CONTRACT_V1"
)
SYNTHETIC_ORDER_SOURCE: Final = "SYNTHETIC_SCHWAB_ORDER_CONTRACT_V1"
SYNTHETIC_ATTEMPT_OUTCOMES: Final = frozenset(
    {"ACCEPTED", "REJECTED", "ACK_LOST"}
)
SYNTHETIC_TERMINAL_STATUSES: Final = frozenset(
    {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
)
_SNAPSHOT_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "mode",
        "networkAccess",
        "credentialsAccepted",
        "brokerActionAllowed",
        "transmitting",
        "retryAllowed",
        "orderTransmission",
        "attempts",
        "orders",
    }
)
_ATTEMPT_KEYS: Final = frozenset(
    {
        "commandId",
        "sequenceId",
        "accountBindingCommitment",
        "attemptedAt",
        "outcome",
    }
)
_ORDER_KEYS: Final = frozenset(
    {
        "providerOrderId",
        "commandId",
        "sequenceId",
        "accountBindingCommitment",
        "symbol",
        "side",
        "requestedQuantity",
        "orderType",
        "limitPrice",
        "intentCreatedAt",
        "status",
        "enteredAt",
        "updatedAt",
        "filledQuantity",
        "remainingQuantity",
        "averageFillPrice",
        "revision",
    }
)
_QUANTITY_TOLERANCE = 1e-9


class SyntheticOrderContractError(ValueError):
    pass


@dataclass(frozen=True)
class SyntheticAttemptRecord:
    attempt: CanarySubmissionAttempt
    outcome: str

    def to_dict(self) -> dict[str, object]:
        return {
            "commandId": self.attempt.command_id,
            "sequenceId": self.attempt.sequence_id,
            "accountBindingCommitment": self.attempt.account_binding_commitment,
            "attemptedAt": _canonical_timestamp(self.attempt.attempted_at),
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class SyntheticOrderRecord:
    provider_order_id: str
    intent: CanaryOrderIntent
    status: str
    entered_at: str
    updated_at: str
    filled_quantity: float
    remaining_quantity: float
    average_fill_price: float | None
    revision: int

    def to_dict(self) -> dict[str, object]:
        return {
            "providerOrderId": self.provider_order_id,
            "commandId": self.intent.command_id,
            "sequenceId": self.intent.sequence_id,
            "accountBindingCommitment": self.intent.account_binding_commitment,
            "symbol": self.intent.symbol,
            "side": self.intent.side,
            "requestedQuantity": self.intent.quantity,
            "orderType": self.intent.order_type,
            "limitPrice": self.intent.limit_price,
            "intentCreatedAt": _canonical_timestamp(self.intent.created_at),
            "status": self.status,
            "enteredAt": _canonical_timestamp(self.entered_at),
            "updatedAt": _canonical_timestamp(self.updated_at),
            "filledQuantity": self.filled_quantity,
            "remainingQuantity": self.remaining_quantity,
            "averageFillPrice": self.average_fill_price,
            "revision": self.revision,
        }

    def observation(self, *, observed_at: str) -> CanaryBrokerOrderObservation:
        observed = _require_timestamp(observed_at, field="observation")
        updated = _require_timestamp(self.updated_at, field="order update")
        if observed < updated:
            raise SyntheticOrderContractError(
                "Synthetic observation time cannot predate the latest order update."
            )
        return CanaryBrokerOrderObservation(
            provider_order_id=self.provider_order_id,
            client_command_id=self.intent.command_id,
            source=SYNTHETIC_ORDER_SOURCE,
            account_binding_commitment=self.intent.account_binding_commitment,
            symbol=self.intent.symbol,
            side=self.intent.side,
            requested_quantity=self.intent.quantity,
            filled_quantity=self.filled_quantity,
            remaining_quantity=self.remaining_quantity,
            average_fill_price=self.average_fill_price,
            order_type=self.intent.order_type,
            status=self.status,
            entered_at=self.entered_at,
            updated_at=self.updated_at,
            observed_at=observed.isoformat(),
        )


class SyntheticSchwabOrderContractEmulator:
    """Local state machine that cannot contact or act on a brokerage account."""

    def __init__(self) -> None:
        self._attempts: dict[str, SyntheticAttemptRecord] = {}
        self._orders: dict[str, SyntheticOrderRecord] = {}

    @property
    def capabilities(self) -> dict[str, object]:
        return {
            "schemaVersion": SYNTHETIC_ORDER_CONTRACT_SCHEMA_VERSION,
            "mode": "SANITIZED_SYNTHETIC_CONTRACT_ONLY",
            "networkAccess": False,
            "credentialsAccepted": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "retryAllowed": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def record_synthetic_attempt(
        self,
        *,
        intent: CanaryOrderIntent,
        attempted_at: str,
        outcome: str,
    ) -> CanarySubmissionAttempt:
        attempted = _require_timestamp(attempted_at, field="attempt")
        created = _require_timestamp(intent.created_at, field="intent creation")
        if attempted < created:
            raise SyntheticOrderContractError(
                "Synthetic attempt time cannot predate intent creation."
            )
        normalized_outcome = str(outcome).strip().upper()
        if normalized_outcome not in SYNTHETIC_ATTEMPT_OUTCOMES:
            raise SyntheticOrderContractError(
                "Synthetic attempt outcome must be ACCEPTED, REJECTED, or ACK_LOST."
            )
        attempt = CanarySubmissionAttempt(
            command_id=intent.command_id,
            sequence_id=intent.sequence_id,
            account_binding_commitment=intent.account_binding_commitment,
            attempted_at=attempted.isoformat(),
        )
        existing = self._attempts.get(intent.command_id)
        proposed = SyntheticAttemptRecord(attempt=attempt, outcome=normalized_outcome)
        if existing is not None:
            if existing == proposed:
                return existing.attempt
            raise SyntheticOrderContractError(
                "A synthetic command attempt already exists and cannot be retried or changed."
            )
        self._attempts[intent.command_id] = proposed
        if normalized_outcome != "ACK_LOST":
            status = "PENDING_ACK" if normalized_outcome == "ACCEPTED" else "REJECTED"
            self._orders[intent.command_id] = SyntheticOrderRecord(
                provider_order_id=_provider_order_id(intent.command_id),
                intent=intent,
                status=status,
                entered_at=attempted.isoformat(),
                updated_at=attempted.isoformat(),
                filled_quantity=0.0,
                remaining_quantity=float(intent.quantity),
                average_fill_price=None,
                revision=1,
            )
        return attempt

    def attempt_for(self, command_id: str) -> CanarySubmissionAttempt | None:
        record = self._attempts.get(str(command_id))
        return record.attempt if record is not None else None

    def order_for(self, command_id: str) -> SyntheticOrderRecord | None:
        return self._orders.get(str(command_id))

    def record_synthetic_acknowledgement(
        self,
        *,
        command_id: str,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        record = self._require_order(command_id)
        if record.status == "WORKING":
            return self._require_same_update(record, updated_at)
        if record.status != "PENDING_ACK":
            raise SyntheticOrderContractError(
                f"Synthetic acknowledgement cannot follow {record.status}."
            )
        return self._replace_status(record, status="WORKING", updated_at=updated_at)

    def record_synthetic_fill(
        self,
        *,
        command_id: str,
        fill_quantity: float,
        fill_price: float,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        record = self._require_order(command_id)
        if record.status in SYNTHETIC_TERMINAL_STATUSES:
            raise SyntheticOrderContractError(
                f"A terminal synthetic order cannot receive a fill: {record.status}."
            )
        if record.status not in {
            "PENDING_ACK",
            "WORKING",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
        }:
            raise SyntheticOrderContractError(
                f"Synthetic fill cannot follow {record.status}."
            )
        quantity = _require_positive_number(fill_quantity, field="fill quantity")
        price = _require_positive_number(fill_price, field="fill price")
        if quantity - record.remaining_quantity > _QUANTITY_TOLERANCE:
            raise SyntheticOrderContractError(
                "Synthetic fill quantity exceeds the remaining order quantity."
            )
        updated = self._require_later_update(record, updated_at)
        previous_value = (
            0.0
            if record.average_fill_price is None
            else record.average_fill_price * record.filled_quantity
        )
        filled = record.filled_quantity + quantity
        remaining = max(0.0, record.remaining_quantity - quantity)
        average = (previous_value + (quantity * price)) / filled
        status = "FILLED" if isclose(
            remaining, 0.0, rel_tol=0.0, abs_tol=_QUANTITY_TOLERANCE
        ) else "PARTIALLY_FILLED"
        updated_record = replace(
            record,
            status=status,
            updated_at=updated.isoformat(),
            filled_quantity=filled,
            remaining_quantity=remaining,
            average_fill_price=average,
            revision=record.revision + 1,
        )
        self._orders[record.intent.command_id] = updated_record
        return updated_record

    def record_synthetic_cancel_request(
        self,
        *,
        command_id: str,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        record = self._require_order(command_id)
        if record.status == "CANCEL_PENDING":
            return self._require_same_update(record, updated_at)
        if record.status not in {"PENDING_ACK", "WORKING", "PARTIALLY_FILLED"}:
            raise SyntheticOrderContractError(
                f"Synthetic cancel request cannot follow {record.status}."
            )
        return self._replace_status(
            record,
            status="CANCEL_PENDING",
            updated_at=updated_at,
        )

    def record_synthetic_cancel_confirmation(
        self,
        *,
        command_id: str,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        record = self._require_order(command_id)
        if record.status == "CANCELED":
            return self._require_same_update(record, updated_at)
        if record.status != "CANCEL_PENDING":
            raise SyntheticOrderContractError(
                f"Synthetic cancel confirmation cannot follow {record.status}."
            )
        return self._replace_status(
            record,
            status="CANCELED",
            updated_at=updated_at,
        )

    def record_synthetic_expiration(
        self,
        *,
        command_id: str,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        record = self._require_order(command_id)
        if record.status == "EXPIRED":
            return self._require_same_update(record, updated_at)
        if record.status not in {"PENDING_ACK", "WORKING", "PARTIALLY_FILLED"}:
            raise SyntheticOrderContractError(
                f"Synthetic expiration cannot follow {record.status}."
            )
        return self._replace_status(
            record,
            status="EXPIRED",
            updated_at=updated_at,
        )

    def observe_synthetic_order(
        self,
        *,
        command_id: str,
        observed_at: str,
    ) -> CanaryBrokerOrderObservation:
        return self._require_order(command_id).observation(
            observed_at=observed_at
        )

    def snapshot(self) -> dict[str, object]:
        return {
            **self.capabilities,
            "attempts": [
                self._attempts[key].to_dict() for key in sorted(self._attempts)
            ],
            "orders": [
                self._orders[key].to_dict() for key in sorted(self._orders)
            ],
        }

    def snapshot_json(self) -> str:
        return json.dumps(
            self.snapshot(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, object],
    ) -> SyntheticSchwabOrderContractEmulator:
        payload = dict(snapshot)
        if frozenset(payload) != _SNAPSHOT_KEYS:
            raise SyntheticOrderContractError(
                "Synthetic order-contract snapshot fields do not match the schema."
            )
        expected_capabilities = cls().capabilities
        for key, expected in expected_capabilities.items():
            if payload.get(key) != expected:
                raise SyntheticOrderContractError(
                    f"Synthetic order-contract capability changed: {key}."
                )
        attempts_payload = payload.get("attempts")
        orders_payload = payload.get("orders")
        if not isinstance(attempts_payload, list) or not isinstance(
            orders_payload, list
        ):
            raise SyntheticOrderContractError(
                "Synthetic order-contract attempts and orders must be lists."
            )
        emulator = cls()
        for item in attempts_payload:
            attempt_record = _attempt_from_dict(item)
            command_id = attempt_record.attempt.command_id
            if command_id in emulator._attempts:
                raise SyntheticOrderContractError(
                    "Synthetic snapshot contains a duplicate command attempt."
                )
            emulator._attempts[command_id] = attempt_record
        for item in orders_payload:
            order = _order_from_dict(item)
            command_id = order.intent.command_id
            if command_id in emulator._orders:
                raise SyntheticOrderContractError(
                    "Synthetic snapshot contains duplicate order identity."
                )
            attempt_record = emulator._attempts.get(command_id)
            if attempt_record is None:
                raise SyntheticOrderContractError(
                    "Synthetic snapshot order has no matching attempt."
                )
            _validate_attempt_order_pair(attempt_record, order)
            emulator._orders[command_id] = order
        for command_id, attempt_record in emulator._attempts.items():
            has_order = command_id in emulator._orders
            if attempt_record.outcome == "ACK_LOST" and has_order:
                raise SyntheticOrderContractError(
                    "ACK_LOST synthetic attempt cannot contain broker order evidence."
                )
            if attempt_record.outcome != "ACK_LOST" and not has_order:
                raise SyntheticOrderContractError(
                    "Accepted or rejected synthetic attempt is missing order evidence."
                )
        return emulator

    @classmethod
    def from_snapshot_json(
        cls,
        value: str,
    ) -> SyntheticSchwabOrderContractEmulator:
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SyntheticOrderContractError(
                "Synthetic order-contract snapshot JSON is invalid."
            ) from exc
        if not isinstance(payload, dict):
            raise SyntheticOrderContractError(
                "Synthetic order-contract snapshot JSON must contain an object."
            )
        return cls.from_snapshot(payload)

    def _require_order(self, command_id: str) -> SyntheticOrderRecord:
        record = self._orders.get(str(command_id))
        if record is None:
            raise SyntheticOrderContractError(
                "Synthetic order evidence does not exist for this command."
            )
        return record

    def _replace_status(
        self,
        record: SyntheticOrderRecord,
        *,
        status: str,
        updated_at: str,
    ) -> SyntheticOrderRecord:
        updated = self._require_later_update(record, updated_at)
        changed = replace(
            record,
            status=status,
            updated_at=updated.isoformat(),
            revision=record.revision + 1,
        )
        self._orders[record.intent.command_id] = changed
        return changed

    @staticmethod
    def _require_later_update(
        record: SyntheticOrderRecord,
        value: str,
    ) -> datetime:
        updated = _require_timestamp(value, field="order update")
        previous = _require_timestamp(record.updated_at, field="prior order update")
        if updated <= previous:
            raise SyntheticOrderContractError(
                "Synthetic order update time must move strictly forward."
            )
        return updated

    @staticmethod
    def _require_same_update(
        record: SyntheticOrderRecord,
        value: str,
    ) -> SyntheticOrderRecord:
        if _canonical_timestamp(value) != _canonical_timestamp(record.updated_at):
            raise SyntheticOrderContractError(
                "Idempotent synthetic transition must repeat the exact update time."
            )
        return record


def _attempt_from_dict(value: object) -> SyntheticAttemptRecord:
    item = _require_mapping(value, field="attempt")
    if frozenset(item) != _ATTEMPT_KEYS:
        raise SyntheticOrderContractError(
            "Synthetic attempt fields do not match the schema."
        )
    outcome = str(item["outcome"]).strip().upper()
    if outcome not in SYNTHETIC_ATTEMPT_OUTCOMES:
        raise SyntheticOrderContractError(
            "Synthetic attempt snapshot has an unsupported outcome."
        )
    attempt = CanarySubmissionAttempt(
        command_id=str(item["commandId"]),
        sequence_id=str(item["sequenceId"]),
        account_binding_commitment=str(item["accountBindingCommitment"]),
        attempted_at=_canonical_timestamp(item["attemptedAt"]),
    )
    _require_timestamp(attempt.attempted_at, field="attempt")
    return SyntheticAttemptRecord(attempt=attempt, outcome=outcome)


def _order_from_dict(value: object) -> SyntheticOrderRecord:
    item = _require_mapping(value, field="order")
    if frozenset(item) != _ORDER_KEYS:
        raise SyntheticOrderContractError(
            "Synthetic order fields do not match the schema."
        )
    intent = CanaryOrderIntent(
        sequence_id=str(item["sequenceId"]),
        account_binding_commitment=str(item["accountBindingCommitment"]),
        symbol=str(item["symbol"]),
        side=str(item["side"]),
        quantity=_require_positive_number(
            item["requestedQuantity"], field="requested quantity"
        ),
        order_type=str(item["orderType"]),
        limit_price=(
            None
            if item["limitPrice"] is None
            else _require_positive_number(item["limitPrice"], field="limit price")
        ),
        created_at=_canonical_timestamp(item["intentCreatedAt"]),
    )
    if item["commandId"] != intent.command_id:
        raise SyntheticOrderContractError(
            "Synthetic snapshot command identity does not match its order intent."
        )
    provider_order_id = str(item["providerOrderId"])
    if provider_order_id != _provider_order_id(intent.command_id):
        raise SyntheticOrderContractError(
            "Synthetic snapshot provider order identity is invalid."
        )
    status = str(item["status"]).strip().upper()
    if status not in {
        "PENDING_ACK",
        "WORKING",
        "PARTIALLY_FILLED",
        "CANCEL_PENDING",
        "FILLED",
        "CANCELED",
        "REJECTED",
        "EXPIRED",
    }:
        raise SyntheticOrderContractError(
            "Synthetic snapshot order status is unsupported."
        )
    entered_at = _canonical_timestamp(item["enteredAt"])
    updated_at = _canonical_timestamp(item["updatedAt"])
    entered = _require_timestamp(entered_at, field="order entry")
    updated = _require_timestamp(updated_at, field="order update")
    if updated < entered:
        raise SyntheticOrderContractError(
            "Synthetic snapshot order update predates entry."
        )
    filled = _require_nonnegative_number(
        item["filledQuantity"], field="filled quantity"
    )
    remaining = _require_nonnegative_number(
        item["remainingQuantity"], field="remaining quantity"
    )
    if not isclose(
        filled + remaining,
        float(intent.quantity),
        rel_tol=0.0,
        abs_tol=_QUANTITY_TOLERANCE,
    ):
        raise SyntheticOrderContractError(
            "Synthetic snapshot order quantities do not reconcile."
        )
    average = item["averageFillPrice"]
    if filled > 0:
        average = _require_positive_number(average, field="average fill price")
    elif average is not None:
        raise SyntheticOrderContractError(
            "Synthetic snapshot has an average fill price without a fill."
        )
    revision = item["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise SyntheticOrderContractError(
            "Synthetic snapshot revision must be a positive integer."
        )
    if status in {"PENDING_ACK", "REJECTED"} and revision != 1:
        raise SyntheticOrderContractError(
            f"Synthetic {status} snapshot must remain at initial revision 1."
        )
    if status not in {"PENDING_ACK", "REJECTED"} and revision < 2:
        raise SyntheticOrderContractError(
            f"Synthetic {status} snapshot requires lifecycle revision 2 or later."
        )
    if status == "FILLED" and not isclose(
        remaining, 0.0, rel_tol=0.0, abs_tol=_QUANTITY_TOLERANCE
    ):
        raise SyntheticOrderContractError(
            "Synthetic FILLED snapshot must have no remaining quantity."
        )
    if status == "PARTIALLY_FILLED" and not (filled > 0 and remaining > 0):
        raise SyntheticOrderContractError(
            "Synthetic partial-fill snapshot quantities are invalid."
        )
    if status in {"PENDING_ACK", "WORKING", "REJECTED"} and filled != 0:
        raise SyntheticOrderContractError(
            f"Synthetic {status} snapshot cannot contain a fill."
        )
    return SyntheticOrderRecord(
        provider_order_id=provider_order_id,
        intent=intent,
        status=status,
        entered_at=entered_at,
        updated_at=updated_at,
        filled_quantity=filled,
        remaining_quantity=remaining,
        average_fill_price=average,
        revision=revision,
    )


def _validate_attempt_order_pair(
    attempt_record: SyntheticAttemptRecord,
    order: SyntheticOrderRecord,
) -> None:
    attempt = attempt_record.attempt
    if (
        attempt.command_id != order.intent.command_id
        or attempt.sequence_id != order.intent.sequence_id
        or attempt.account_binding_commitment
        != order.intent.account_binding_commitment
    ):
        raise SyntheticOrderContractError(
            "Synthetic snapshot attempt and order identities do not match."
        )
    attempted = _require_timestamp(attempt.attempted_at, field="attempt")
    entered = _require_timestamp(order.entered_at, field="order entry")
    if attempted != entered:
        raise SyntheticOrderContractError(
            "Synthetic snapshot order entry must equal its attempt time."
        )
    if attempt_record.outcome == "REJECTED" and order.status != "REJECTED":
        raise SyntheticOrderContractError(
            "Rejected synthetic attempt must retain REJECTED order status."
        )
    if attempt_record.outcome == "ACCEPTED" and order.status == "REJECTED":
        raise SyntheticOrderContractError(
            "Accepted synthetic attempt cannot become REJECTED in this contract."
        )


def _provider_order_id(command_id: str) -> str:
    digest = hashlib.sha256(
        f"{SYNTHETIC_ORDER_CONTRACT_SCHEMA_VERSION}:{command_id}".encode("utf-8")
    ).hexdigest()
    return f"synthetic-provider-{digest[:24]}"


def _require_mapping(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SyntheticOrderContractError(
            f"Synthetic {field} snapshot must contain an object."
        )
    return dict(value)


def _canonical_timestamp(value: object) -> str:
    return _require_timestamp(value, field="timestamp").isoformat()


def _require_timestamp(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyntheticOrderContractError(
            f"Synthetic {field} timestamp is invalid."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SyntheticOrderContractError(
            f"Synthetic {field} timestamp must include a timezone."
        )
    return parsed


def _require_positive_number(value: object, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
        or float(value) <= 0
    ):
        raise SyntheticOrderContractError(
            f"Synthetic {field} must be finite and greater than zero."
        )
    return float(value)


def _require_nonnegative_number(value: object, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
        or float(value) < 0
    ):
        raise SyntheticOrderContractError(
            f"Synthetic {field} must be finite and non-negative."
        )
    return float(value)
