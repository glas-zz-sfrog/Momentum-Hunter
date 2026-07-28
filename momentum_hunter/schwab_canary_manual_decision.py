from __future__ import annotations

"""Write-once human decision boundary for one exact Schwab canary intent."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from typing import Final

from momentum_hunter.schwab_canary_evidence import CanaryPositionEvidenceStore
from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryOrderIntent,
)
from momentum_hunter.schwab_canary_preflight_receipt import (
    RECEIPT_AWAITING_DECISION,
    CanaryPreflightReceiptPolicy,
    CanaryPreflightReceiptStore,
    inspect_canary_preflight_receipt,
)


CANARY_MANUAL_DECISION_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_MANUAL_DECISION_V1"
)
APPROVE_EXACT_CANARY_ORDER: Final = "APPROVE_EXACT_CANARY_ORDER"
DECLINE_CANARY_ORDER: Final = "DECLINE_CANARY_ORDER"
SUPPORTED_DECISIONS: Final = frozenset(
    {
        APPROVE_EXACT_CANARY_ORDER,
        DECLINE_CANARY_ORDER,
    }
)
DECISION_RECORDED: Final = "DECISION_RECORDED"
DECISION_DECLINED: Final = "DECLINED"
DECISION_MISSING: Final = "MISSING"
DECISION_BLOCKED: Final = "BLOCK"
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES: Final = 32_768
_RECORD_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "decisionId",
        "decision",
        "decisionOutcome",
        "decidedAt",
        "actorId",
        "reasonCode",
        "receiptId",
        "receiptSha256",
        "evidenceSetSha256",
        "receiptRecordedAt",
        "receiptExpiresAt",
        "accountEnding",
        "accountType",
        "canaryIntentId",
        "sequenceId",
        "fundingRequirementId",
        "orderCommandId",
        "orderAccountBindingTag",
        "symbol",
        "side",
        "quantity",
        "orderType",
        "limitPrice",
        "maximumDebit",
        "orderIntentCreatedAt",
        "recordSha256",
        "oneWay",
        "replaceSupported",
        "clearSupported",
        "decisionRecorded",
        "manualDecisionRequired",
        "actorAuthentication",
        "operatorPresenceProven",
        "executionPermit",
        "brokerActionAllowed",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
    }
)


class CanaryManualDecisionError(ValueError):
    pass


class CanaryManualDecisionConflict(CanaryManualDecisionError):
    pass


@dataclass(frozen=True, repr=False)
class CanaryManualDecisionPolicy:
    expected_actor_id: str
    expected_order_account_binding_commitment: str
    max_order_intent_age_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        actor_id = _normalize_identifier(
            self.expected_actor_id,
            field="expected actor ID",
        )
        commitment = str(
            self.expected_order_account_binding_commitment
        ).strip().lower()
        if not _HEX_SHA256.fullmatch(commitment):
            raise CanaryManualDecisionError(
                "Expected order account-binding commitment must be a SHA-256."
            )
        if (
            not _is_finite_number(self.max_order_intent_age_seconds)
            or self.max_order_intent_age_seconds <= 0
        ):
            raise CanaryManualDecisionError(
                "Maximum order-intent age must be finite and greater than zero."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryManualDecisionError(
                "Maximum future skew must be finite and non-negative."
            )
        object.__setattr__(self, "expected_actor_id", actor_id)
        object.__setattr__(
            self,
            "expected_order_account_binding_commitment",
            commitment,
        )

    @property
    def order_account_binding_tag(self) -> str:
        return _sha256_text(
            self.expected_order_account_binding_commitment
        )

    def __repr__(self) -> str:
        return (
            "CanaryManualDecisionPolicy("
            f"expected_actor_id={self.expected_actor_id!r}, "
            "expected_order_account_binding=<redacted>, "
            f"max_order_intent_age_seconds="
            f"{self.max_order_intent_age_seconds!r}, "
            f"max_future_skew_seconds={self.max_future_skew_seconds!r})"
        )


@dataclass(frozen=True, repr=False)
class CanaryManualDecisionRecord:
    decision: str
    decided_at: str
    actor_id: str
    reason_code: str
    receipt_id: str
    receipt_sha256: str
    evidence_set_sha256: str
    receipt_recorded_at: str
    receipt_expires_at: str
    account_ending: str
    account_type: str
    canary_intent_id: str
    sequence_id: str
    funding_requirement_id: str
    order_command_id: str
    order_account_binding_tag: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float
    maximum_debit: float
    order_intent_created_at: str

    @property
    def decision_outcome(self) -> str:
        if self.decision == APPROVE_EXACT_CANARY_ORDER:
            return "EXACT_INTENT_APPROVAL_RECORDED_NO_EXECUTION_AUTHORITY"
        return "EXACT_INTENT_DECLINED"

    @property
    def decision_id(self) -> str:
        return f"canary-decision-{_sha256_payload(self._identity_payload())[:24]}"

    @property
    def record_sha256(self) -> str:
        return _sha256_payload(self._unsigned_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "decidedAt": self.decided_at,
            "actorId": self.actor_id,
            "receiptId": self.receipt_id,
            "receiptSha256": self.receipt_sha256,
            "orderCommandId": self.order_command_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "orderType": self.order_type,
            "limitPrice": self.limit_price,
            "maximumDebit": self.maximum_debit,
        }

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_MANUAL_DECISION_SCHEMA_VERSION,
            "decisionId": self.decision_id,
            "decision": self.decision,
            "decisionOutcome": self.decision_outcome,
            "decidedAt": self.decided_at,
            "actorId": self.actor_id,
            "reasonCode": self.reason_code,
            "receiptId": self.receipt_id,
            "receiptSha256": self.receipt_sha256,
            "evidenceSetSha256": self.evidence_set_sha256,
            "receiptRecordedAt": self.receipt_recorded_at,
            "receiptExpiresAt": self.receipt_expires_at,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "canaryIntentId": self.canary_intent_id,
            "sequenceId": self.sequence_id,
            "fundingRequirementId": self.funding_requirement_id,
            "orderCommandId": self.order_command_id,
            "orderAccountBindingTag": self.order_account_binding_tag,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "orderType": self.order_type,
            "limitPrice": self.limit_price,
            "maximumDebit": self.maximum_debit,
            "orderIntentCreatedAt": self.order_intent_created_at,
            "oneWay": True,
            "replaceSupported": False,
            "clearSupported": False,
            "decisionRecorded": True,
            "manualDecisionRequired": True,
            "actorAuthentication": "UNAVAILABLE",
            "operatorPresenceProven": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "recordSha256": self.record_sha256,
        }

    def __repr__(self) -> str:
        return (
            "CanaryManualDecisionRecord("
            f"decision_id={self.decision_id!r}, decision={self.decision!r}, "
            f"decided_at={self.decided_at!r}, actor_id={self.actor_id!r}, "
            f"receipt_id={self.receipt_id!r}, "
            f"order_command_id={self.order_command_id!r}, "
            f"symbol={self.symbol!r}, quantity={self.quantity!r})"
        )


@dataclass(frozen=True)
class CanaryManualDecisionInspection:
    status: str
    conclusion: str
    observed_at: str
    decision_id: str | None
    decision: str | None
    receipt_id: str | None
    findings: tuple[str, ...]

    @property
    def decision_recorded(self) -> bool:
        return self.status in {DECISION_RECORDED, DECISION_DECLINED}

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_MANUAL_DECISION_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "observedAt": self.observed_at,
            "decisionId": self.decision_id,
            "decision": self.decision,
            "receiptId": self.receipt_id,
            "findings": list(self.findings),
            "decisionRecorded": self.decision_recorded,
            "manualDecisionRequired": True,
            "actorAuthentication": "UNAVAILABLE",
            "operatorPresenceProven": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


class CanaryManualDecisionStore:
    """Persist one decision with intentionally no replace, clear, or delete."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def persist(
        self,
        record: CanaryManualDecisionRecord,
    ) -> dict[str, object]:
        payload = record.to_dict()
        encoded = (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise CanaryManualDecisionError(
                "Canary manual decision exceeds the size limit."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                existing = self.load()
            except CanaryManualDecisionError as exc:
                raise CanaryManualDecisionConflict(
                    "A different or invalid canary decision already exists."
                ) from exc
            if existing == payload:
                return existing
            raise CanaryManualDecisionConflict(
                "A different or invalid canary decision already exists."
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Partial evidence remains fail-closed and is not silently removed.
            raise
        persisted = self.load()
        if persisted != payload:
            raise CanaryManualDecisionError(
                "Persisted canary manual decision failed validation."
            )
        return persisted

    def load(self) -> dict[str, object] | None:
        if not self.path.exists():
            return None
        if not self.path.is_file() or self.path.is_symlink():
            raise CanaryManualDecisionError(
                "Canary decision must be a regular non-symlink file."
            )
        size = self.path.stat().st_size
        if size <= 0 or size > _MAX_RECORD_BYTES:
            raise CanaryManualDecisionError(
                "Canary decision has an invalid file size."
            )
        try:
            payload = json.loads(self.path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanaryManualDecisionError(
                "Canary decision is unreadable or malformed."
            ) from exc
        if not isinstance(payload, dict):
            raise CanaryManualDecisionError(
                "Canary decision must contain a JSON object."
            )
        _validate_record_payload(payload)
        return json.loads(_canonical_json(payload))


def build_canary_manual_decision(
    *,
    receipt_store: CanaryPreflightReceiptStore,
    position_evidence_store: CanaryPositionEvidenceStore,
    receipt_policy: CanaryPreflightReceiptPolicy,
    order_intent: CanaryOrderIntent,
    decision: str,
    actor_id: str,
    reason_code: str,
    decided_at: datetime,
    policy: CanaryManualDecisionPolicy,
) -> CanaryManualDecisionRecord:
    """Build a decision record without creating broker or execution authority."""

    normalized_decided_at = _require_aware_datetime(
        decided_at,
        field="decided_at",
    )
    normalized_decision = str(decision).strip().upper()
    if normalized_decision not in SUPPORTED_DECISIONS:
        raise CanaryManualDecisionError(
            "Decision must exactly approve or decline the canary order."
        )
    normalized_actor_id = _normalize_identifier(
        actor_id,
        field="actor ID",
    )
    if normalized_actor_id != policy.expected_actor_id:
        raise CanaryManualDecisionError(
            "Decision actor does not match frozen policy."
        )
    normalized_reason_code = _normalize_identifier(
        reason_code,
        field="reason code",
    )
    receipt_inspection = inspect_canary_preflight_receipt(
        store=receipt_store,
        position_evidence_store=position_evidence_store,
        observed_at=normalized_decided_at,
        policy=receipt_policy,
    )
    if receipt_inspection.status != RECEIPT_AWAITING_DECISION:
        raise CanaryManualDecisionError(
            "A current immutable preflight receipt is required for a decision."
        )
    receipt = receipt_store.load()
    if receipt is None:
        raise CanaryManualDecisionError(
            "The inspected canary receipt disappeared."
        )
    if (
        order_intent.account_binding_commitment
        != policy.expected_order_account_binding_commitment
    ):
        raise CanaryManualDecisionError(
            "Order intent account binding does not match frozen policy."
        )
    evidence = receipt["evidence"]
    position = evidence["positionInvariant"]
    funding = evidence["fundingGate"]
    preflight = evidence["preflight"]
    _validate_order_against_receipt(
        order_intent=order_intent,
        position=position,
        funding=funding,
        preflight=preflight,
        decided_at=normalized_decided_at,
        policy=policy,
    )
    receipt_recorded_at = _parse_timestamp(
        receipt["recordedAt"],
        field="receipt recordedAt",
    )
    if normalized_decided_at < receipt_recorded_at:
        raise CanaryManualDecisionError(
            "A manual decision cannot predate its immutable receipt."
        )
    return CanaryManualDecisionRecord(
        decision=normalized_decision,
        decided_at=normalized_decided_at.isoformat(),
        actor_id=normalized_actor_id,
        reason_code=normalized_reason_code,
        receipt_id=str(receipt["receiptId"]),
        receipt_sha256=str(receipt["receiptSha256"]),
        evidence_set_sha256=str(receipt["evidenceSetSha256"]),
        receipt_recorded_at=str(receipt["recordedAt"]),
        receipt_expires_at=str(receipt["expiresAt"]),
        account_ending=str(preflight["accountEnding"]),
        account_type=str(preflight["accountType"]),
        canary_intent_id=str(preflight["canaryIntentId"]),
        sequence_id=str(preflight["sequenceId"]),
        funding_requirement_id=str(preflight["fundingRequirementId"]),
        order_command_id=order_intent.command_id,
        order_account_binding_tag=policy.order_account_binding_tag,
        symbol=order_intent.symbol,
        side=order_intent.side,
        quantity=order_intent.quantity,
        order_type=order_intent.order_type,
        limit_price=float(order_intent.limit_price),
        maximum_debit=float(funding["maximumDebit"]),
        order_intent_created_at=order_intent.created_at,
    )


def inspect_canary_manual_decision(
    *,
    decision_store: CanaryManualDecisionStore,
    receipt_store: CanaryPreflightReceiptStore,
    position_evidence_store: CanaryPositionEvidenceStore,
    receipt_policy: CanaryPreflightReceiptPolicy,
    decision_policy: CanaryManualDecisionPolicy,
    order_intent: CanaryOrderIntent,
    observed_at: datetime,
) -> CanaryManualDecisionInspection:
    """Revalidate a recorded decision without permitting a broker action."""

    normalized_observed_at = _require_aware_datetime(
        observed_at,
        field="observed_at",
    )
    record = decision_store.load()
    if record is None:
        return CanaryManualDecisionInspection(
            status=DECISION_MISSING,
            conclusion="CANARY_MANUAL_DECISION_MISSING",
            observed_at=normalized_observed_at.isoformat(),
            decision_id=None,
            decision=None,
            receipt_id=None,
            findings=("No immutable canary manual decision exists.",),
        )
    receipt_inspection = inspect_canary_preflight_receipt(
        store=receipt_store,
        position_evidence_store=position_evidence_store,
        observed_at=normalized_observed_at,
        policy=receipt_policy,
    )
    receipt = receipt_store.load()
    if (
        receipt_inspection.status != RECEIPT_AWAITING_DECISION
        or receipt is None
    ):
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_RECEIPT_INVALID",
            finding="The underlying preflight receipt is no longer valid.",
        )
    if (
        record.get("receiptId") != receipt.get("receiptId")
        or record.get("receiptSha256") != receipt.get("receiptSha256")
        or record.get("evidenceSetSha256")
        != receipt.get("evidenceSetSha256")
        or record.get("receiptRecordedAt") != receipt.get("recordedAt")
        or record.get("receiptExpiresAt") != receipt.get("expiresAt")
    ):
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_RECEIPT_MISMATCH",
            finding="The decision no longer matches its exact receipt.",
        )
    if (
        record.get("actorId") != decision_policy.expected_actor_id
        or record.get("orderAccountBindingTag")
        != decision_policy.order_account_binding_tag
    ):
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_POLICY_MISMATCH",
            finding="The decision does not match frozen actor/account policy.",
        )
    try:
        _validate_record_against_order_intent(
            record=record,
            receipt=receipt,
            order_intent=order_intent,
            policy=decision_policy,
        )
    except CanaryManualDecisionError as exc:
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_ORDER_INTENT_MISMATCH",
            finding=str(exc),
        )
    decided_at = _parse_timestamp(record["decidedAt"], field="decidedAt")
    if (
        normalized_observed_at
        < decided_at
        - timedelta(seconds=decision_policy.max_future_skew_seconds)
    ):
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_CLOCK_INVALID",
            finding="Decision inspection time predates the recorded decision.",
        )
    order_created_at = _parse_timestamp(
        record["orderIntentCreatedAt"],
        field="orderIntentCreatedAt",
    )
    age = (decided_at - order_created_at).total_seconds()
    if (
        age < -decision_policy.max_future_skew_seconds
        or age > decision_policy.max_order_intent_age_seconds
    ):
        return _blocked_inspection(
            record=record,
            observed_at=normalized_observed_at,
            conclusion="CANARY_MANUAL_DECISION_ORDER_INTENT_STALE",
            finding="The decision references an invalid-age order intent.",
        )
    decision = str(record["decision"])
    if decision == DECLINE_CANARY_ORDER:
        return CanaryManualDecisionInspection(
            status=DECISION_DECLINED,
            conclusion="EXACT_CANARY_INTENT_DECLINED",
            observed_at=normalized_observed_at.isoformat(),
            decision_id=str(record["decisionId"]),
            decision=decision,
            receipt_id=str(record["receiptId"]),
            findings=(),
        )
    return CanaryManualDecisionInspection(
        status=DECISION_RECORDED,
        conclusion=(
            "EXACT_CANARY_INTENT_APPROVAL_RECORDED_NO_EXECUTION_AUTHORITY"
        ),
        observed_at=normalized_observed_at.isoformat(),
        decision_id=str(record["decisionId"]),
        decision=decision,
        receipt_id=str(record["receiptId"]),
        findings=(),
    )


def _validate_order_against_receipt(
    *,
    order_intent: CanaryOrderIntent,
    position: dict[str, object],
    funding: dict[str, object],
    preflight: dict[str, object],
    decided_at: datetime,
    policy: CanaryManualDecisionPolicy,
) -> None:
    if order_intent.command_id != preflight.get("orderCommandId"):
        raise CanaryManualDecisionError(
            "Order intent command does not match the preflight receipt."
        )
    if order_intent.sequence_id != preflight.get("sequenceId"):
        raise CanaryManualDecisionError(
            "Order intent sequence does not match the preflight receipt."
        )
    if order_intent.symbol != position.get("canarySymbol"):
        raise CanaryManualDecisionError(
            "Order intent symbol does not match the canary position intent."
        )
    if order_intent.quantity != position.get("expectedQuantity"):
        raise CanaryManualDecisionError(
            "Order intent quantity does not match the canary position intent."
        )
    if order_intent.side != "BUY":
        raise CanaryManualDecisionError(
            "The zero-position plumbing canary permits only an exact BUY intent."
        )
    if order_intent.order_type != "LIMIT" or order_intent.limit_price is None:
        raise CanaryManualDecisionError(
            "The bounded plumbing canary requires an exact LIMIT intent."
        )
    maximum_debit = _positive_decimal(
        funding.get("maximumDebit"),
        field="maximum debit",
    )
    quantity = _positive_decimal(
        order_intent.quantity,
        field="order quantity",
    )
    limit_price = _positive_decimal(
        order_intent.limit_price,
        field="limit price",
    )
    if quantity * limit_price > maximum_debit:
        raise CanaryManualDecisionError(
            "Order intent exceeds the independently proven maximum debit."
        )
    intent_created_at = _parse_timestamp(
        order_intent.created_at,
        field="order intent createdAt",
    )
    age = (decided_at - intent_created_at).total_seconds()
    if age < 0:
        raise CanaryManualDecisionError(
            "Order intent timestamp is in the future."
        )
    if age > policy.max_order_intent_age_seconds:
        raise CanaryManualDecisionError(
            "Order intent is older than frozen policy allows."
        )


def _validate_record_against_order_intent(
    *,
    record: dict[str, object],
    receipt: dict[str, object],
    order_intent: CanaryOrderIntent,
    policy: CanaryManualDecisionPolicy,
) -> None:
    if (
        order_intent.account_binding_commitment
        != policy.expected_order_account_binding_commitment
    ):
        raise CanaryManualDecisionError(
            "Current order intent account binding changed."
        )
    evidence = receipt["evidence"]
    funding = evidence["fundingGate"]
    expected = {
        "orderCommandId": order_intent.command_id,
        "sequenceId": order_intent.sequence_id,
        "symbol": order_intent.symbol,
        "side": order_intent.side,
        "quantity": order_intent.quantity,
        "orderType": order_intent.order_type,
        "limitPrice": order_intent.limit_price,
        "maximumDebit": funding["maximumDebit"],
        "orderIntentCreatedAt": order_intent.created_at,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise CanaryManualDecisionError(
                f"Recorded {key} no longer matches the exact order intent."
            )


def _validate_record_payload(payload: dict[str, object]) -> None:
    if set(payload) != _RECORD_KEYS:
        raise CanaryManualDecisionError(
            "Canary decision fields do not match the frozen schema."
        )
    if payload.get("schemaVersion") != CANARY_MANUAL_DECISION_SCHEMA_VERSION:
        raise CanaryManualDecisionError(
            "Canary decision schema is unsupported."
        )
    decision = payload.get("decision")
    if decision not in SUPPORTED_DECISIONS:
        raise CanaryManualDecisionError(
            "Canary decision value is unsupported."
        )
    expected_outcome = (
        "EXACT_INTENT_APPROVAL_RECORDED_NO_EXECUTION_AUTHORITY"
        if decision == APPROVE_EXACT_CANARY_ORDER
        else "EXACT_INTENT_DECLINED"
    )
    if payload.get("decisionOutcome") != expected_outcome:
        raise CanaryManualDecisionError(
            "Canary decision outcome contradicts the decision."
        )
    if (
        payload.get("oneWay") is not True
        or payload.get("replaceSupported") is not False
        or payload.get("clearSupported") is not False
        or payload.get("decisionRecorded") is not True
        or payload.get("manualDecisionRequired") is not True
        or payload.get("actorAuthentication") != "UNAVAILABLE"
        or payload.get("operatorPresenceProven") is not False
        or payload.get("executionPermit") is not False
        or payload.get("brokerActionAllowed") is not False
        or payload.get("retryAllowed") is not False
        or payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise CanaryManualDecisionError(
            "Canary decision safety flags are invalid."
        )
    for key in (
        "receiptSha256",
        "evidenceSetSha256",
        "orderAccountBindingTag",
        "recordSha256",
    ):
        if not _HEX_SHA256.fullmatch(str(payload.get(key, ""))):
            raise CanaryManualDecisionError(
                f"Canary decision {key} is not a SHA-256."
            )
    for key in (
        "decisionId",
        "actorId",
        "reasonCode",
        "receiptId",
        "canaryIntentId",
        "sequenceId",
        "fundingRequirementId",
        "orderCommandId",
    ):
        _normalize_identifier(str(payload.get(key, "")), field=key)
    decided_at = _parse_timestamp(payload["decidedAt"], field="decidedAt")
    receipt_recorded_at = _parse_timestamp(
        payload["receiptRecordedAt"],
        field="receiptRecordedAt",
    )
    expires_at = _parse_timestamp(
        payload["receiptExpiresAt"],
        field="receiptExpiresAt",
    )
    created_at = _parse_timestamp(
        payload["orderIntentCreatedAt"],
        field="orderIntentCreatedAt",
    )
    if (
        decided_at < receipt_recorded_at
        or decided_at > expires_at
        or created_at > decided_at
    ):
        raise CanaryManualDecisionError(
            "Canary decision chronology is invalid."
        )
    ending = str(payload.get("accountEnding", ""))
    if len(ending) != 4 or not ending.isdigit():
        raise CanaryManualDecisionError(
            "Canary decision account ending is invalid."
        )
    if not str(payload.get("accountType", "")).strip():
        raise CanaryManualDecisionError(
            "Canary decision account type is missing."
        )
    if (
        str(payload.get("symbol", "")).strip().upper()
        != payload.get("symbol")
        or payload.get("side") != "BUY"
        or payload.get("orderType") != "LIMIT"
    ):
        raise CanaryManualDecisionError(
            "Canary decision order identity is invalid."
        )
    quantity = _positive_decimal(payload.get("quantity"), field="quantity")
    limit_price = _positive_decimal(
        payload.get("limitPrice"),
        field="limitPrice",
    )
    maximum_debit = _positive_decimal(
        payload.get("maximumDebit"),
        field="maximumDebit",
    )
    if quantity * limit_price > maximum_debit:
        raise CanaryManualDecisionError(
            "Canary decision exceeds maximum debit."
        )
    identity_payload = {
        "decision": payload["decision"],
        "decidedAt": payload["decidedAt"],
        "actorId": payload["actorId"],
        "receiptId": payload["receiptId"],
        "receiptSha256": payload["receiptSha256"],
        "orderCommandId": payload["orderCommandId"],
        "symbol": payload["symbol"],
        "side": payload["side"],
        "quantity": payload["quantity"],
        "orderType": payload["orderType"],
        "limitPrice": payload["limitPrice"],
        "maximumDebit": payload["maximumDebit"],
    }
    expected_decision_id = (
        f"canary-decision-{_sha256_payload(identity_payload)[:24]}"
    )
    if payload.get("decisionId") != expected_decision_id:
        raise CanaryManualDecisionError(
            "Canary decision identity changed."
        )
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "recordSha256"
    }
    if payload.get("recordSha256") != _sha256_payload(unsigned):
        raise CanaryManualDecisionError(
            "Canary decision hash changed."
        )


def _blocked_inspection(
    *,
    record: dict[str, object],
    observed_at: datetime,
    conclusion: str,
    finding: str,
) -> CanaryManualDecisionInspection:
    return CanaryManualDecisionInspection(
        status=DECISION_BLOCKED,
        conclusion=conclusion,
        observed_at=observed_at.isoformat(),
        decision_id=str(record["decisionId"]),
        decision=str(record["decision"]),
        receipt_id=str(record["receiptId"]),
        findings=(finding,),
    )


def _positive_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise CanaryManualDecisionError(
            f"{field} must be a positive finite number."
        )
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CanaryManualDecisionError(
            f"{field} must be a positive finite number."
        ) from exc
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise CanaryManualDecisionError(
            f"{field} must be a positive finite number."
        )
    return decimal_value


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = str(value).strip()
    if not _SIMPLE_IDENTIFIER.fullmatch(normalized):
        raise CanaryManualDecisionError(
            f"{field} must be a simple ASCII identifier."
        )
    return normalized


def _parse_timestamp(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryManualDecisionError(
            f"{field} must be a valid ISO-8601 timestamp."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryManualDecisionError(
            f"{field} must be timezone-aware."
        )
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )
