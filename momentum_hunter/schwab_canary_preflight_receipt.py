from __future__ import annotations

"""Write-once receipt for one exact, nontransmitting canary preflight."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from typing import Final

from momentum_hunter.schwab_canary_evidence import (
    PRE_CANARY_VERIFIED,
    CanaryPositionEvidenceError,
    CanaryPositionEvidenceStore,
)
from momentum_hunter.schwab_canary_funding import (
    CANARY_FUNDING_SCHEMA_VERSION,
    RESTRICTIONS_CLEAR,
    CanaryFundingResult,
)
from momentum_hunter.schwab_canary_order_reconciliation import (
    CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION,
    CanaryOrderReconciliationResult,
)
from momentum_hunter.schwab_canary_positions import (
    POSITION_INVARIANT_SCHEMA_VERSION,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_canary_preflight import (
    CANARY_PREFLIGHT_SCHEMA_VERSION,
    NO_PRIOR_SUBMISSION_EVIDENCE,
    PREFLIGHT_READY,
    PREFLIGHT_READY_CONCLUSION,
    CanaryPreflightPolicy,
    CanaryPreflightResult,
    evaluate_canary_preflight,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CANARY_STOP_SCHEMA_VERSION,
    CREDENTIAL_REVOKED,
    CanaryStopDrillResult,
)


CANARY_PREFLIGHT_RECEIPT_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_PREFLIGHT_RECEIPT_V1"
)
RECEIPT_AWAITING_DECISION: Final = "AWAITING_STEVEN_DECISION"
RECEIPT_EXPIRED: Final = "EXPIRED"
RECEIPT_MISSING: Final = "MISSING"
RECEIPT_BLOCKED: Final = "BLOCK"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECEIPT_BYTES: Final = 131_072
_MAX_DECISION_WINDOW_SECONDS: Final = 300.0
_EVIDENCE_KEYS: Final = frozenset(
    {
        "positionInvariant",
        "fundingGate",
        "orderReconciliation",
        "independentStopDrill",
        "preflight",
    }
)
_RECEIPT_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "receiptId",
        "recordedAt",
        "expiresAt",
        "decisionWindowSeconds",
        "positionChainSha256",
        "evidence",
        "evidenceSetSha256",
        "receiptSha256",
        "oneWay",
        "replaceSupported",
        "clearSupported",
        "manualDecisionRequired",
        "executionPermit",
        "realOrderApproval",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
    }
)


class CanaryPreflightReceiptError(ValueError):
    pass


class CanaryPreflightReceiptConflict(CanaryPreflightReceiptError):
    pass


@dataclass(frozen=True)
class CanaryPreflightReceiptPolicy:
    decision_window_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        if (
            not _is_finite_number(self.decision_window_seconds)
            or self.decision_window_seconds <= 0
            or self.decision_window_seconds > _MAX_DECISION_WINDOW_SECONDS
        ):
            raise CanaryPreflightReceiptError(
                "Decision window must be finite, greater than zero, and no more "
                "than five minutes."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryPreflightReceiptError(
                "Maximum future skew must be finite and non-negative."
            )


@dataclass(frozen=True, repr=False)
class CanaryPreflightReceipt:
    recorded_at: str
    expires_at: str
    decision_window_seconds: float
    position_chain_sha256: str
    position_result: CanaryPositionInvariantResult
    funding_result: CanaryFundingResult
    order_result: CanaryOrderReconciliationResult
    stop_result: CanaryStopDrillResult
    preflight_result: CanaryPreflightResult

    @property
    def evidence(self) -> dict[str, object]:
        return {
            "positionInvariant": self.position_result.to_dict(),
            "fundingGate": self.funding_result.to_dict(),
            "orderReconciliation": self.order_result.to_dict(),
            "independentStopDrill": self.stop_result.to_dict(),
            "preflight": self.preflight_result.to_dict(),
        }

    @property
    def evidence_set_sha256(self) -> str:
        return _sha256_payload(
            {
                "positionChainSha256": self.position_chain_sha256,
                "evidence": self.evidence,
            }
        )

    @property
    def receipt_id(self) -> str:
        return f"canary-preflight-receipt-{self.evidence_set_sha256[:24]}"

    @property
    def receipt_sha256(self) -> str:
        return _sha256_payload(self._unsigned_payload())

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
            "receiptId": self.receipt_id,
            "recordedAt": self.recorded_at,
            "expiresAt": self.expires_at,
            "decisionWindowSeconds": self.decision_window_seconds,
            "positionChainSha256": self.position_chain_sha256,
            "evidence": self.evidence,
            "evidenceSetSha256": self.evidence_set_sha256,
            "oneWay": True,
            "replaceSupported": False,
            "clearSupported": False,
            "manualDecisionRequired": True,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "receiptSha256": self.receipt_sha256,
        }

    def __repr__(self) -> str:
        return (
            "CanaryPreflightReceipt("
            f"receipt_id={self.receipt_id!r}, "
            f"recorded_at={self.recorded_at!r}, "
            f"expires_at={self.expires_at!r}, "
            f"evidence_set_sha256={self.evidence_set_sha256!r})"
        )


@dataclass(frozen=True)
class CanaryPreflightReceiptInspection:
    status: str
    conclusion: str
    observed_at: str
    receipt_id: str | None
    expires_at: str | None
    findings: tuple[str, ...]

    @property
    def awaiting_manual_decision(self) -> bool:
        return self.status == RECEIPT_AWAITING_DECISION

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "observedAt": self.observed_at,
            "receiptId": self.receipt_id,
            "expiresAt": self.expires_at,
            "findings": list(self.findings),
            "awaitingManualDecision": self.awaiting_manual_decision,
            "manualDecisionRequired": True,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


class CanaryPreflightReceiptStore:
    """Persist one exact receipt with no replace, clear, or delete operation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def persist(self, receipt: CanaryPreflightReceipt) -> dict[str, object]:
        payload = receipt.to_dict()
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
        if len(encoded) > _MAX_RECEIPT_BYTES:
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt exceeds the size limit."
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
            except CanaryPreflightReceiptError as exc:
                raise CanaryPreflightReceiptConflict(
                    "A different or invalid canary preflight receipt already exists."
                ) from exc
            if existing == payload:
                return existing
            raise CanaryPreflightReceiptConflict(
                "A different or invalid canary preflight receipt already exists."
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Partial evidence remains fail-closed and is never silently removed.
            raise
        persisted = self.load()
        if persisted != payload:
            raise CanaryPreflightReceiptError(
                "Persisted canary preflight receipt failed validation."
            )
        return persisted

    def load(self) -> dict[str, object] | None:
        if not self.path.exists():
            return None
        if not self.path.is_file() or self.path.is_symlink():
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt must be a regular non-symlink file."
            )
        size = self.path.stat().st_size
        if size <= 0 or size > _MAX_RECEIPT_BYTES:
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt has an invalid file size."
            )
        try:
            payload = json.loads(self.path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt is unreadable or malformed."
            ) from exc
        if not isinstance(payload, dict):
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt must contain a JSON object."
            )
        _validate_receipt_payload(payload)
        return json.loads(_canonical_json(payload))


def build_canary_preflight_receipt(
    *,
    evidence_store: CanaryPositionEvidenceStore,
    position_result: CanaryPositionInvariantResult,
    funding_result: CanaryFundingResult,
    order_result: CanaryOrderReconciliationResult,
    stop_result: CanaryStopDrillResult,
    preflight_evaluated_at: datetime,
    preflight_policy: CanaryPreflightPolicy,
    recorded_at: datetime,
    receipt_policy: CanaryPreflightReceiptPolicy,
) -> CanaryPreflightReceipt:
    """Re-evaluate and bind the exact redacted evidence set used for preflight."""

    normalized_preflight_at = _require_aware_datetime(
        preflight_evaluated_at,
        field="preflight_evaluated_at",
    )
    normalized_recorded_at = _require_aware_datetime(
        recorded_at,
        field="recorded_at",
    )
    preflight_result = evaluate_canary_preflight(
        evidence_store=evidence_store,
        position_result=position_result,
        funding_result=funding_result,
        order_result=order_result,
        stop_result=stop_result,
        evaluated_at=normalized_preflight_at,
        policy=preflight_policy,
    )
    if not preflight_result.ready_for_manual_decision:
        raise CanaryPreflightReceiptError(
            "A receipt requires a complete preflight awaiting Steven's decision."
        )
    try:
        chain = evidence_store.load()
    except (CanaryPositionEvidenceError, OSError) as exc:
        raise CanaryPreflightReceiptError(
            "The position evidence chain could not be revalidated for receipt."
        ) from exc
    if (
        chain.get("chainState") != PRE_CANARY_VERIFIED
        or chain.get("entries") != [
            entry
            for entry in chain.get("entries", [])
            if isinstance(entry, dict)
            and entry.get("result") == position_result.to_dict()
        ]
        or len(chain.get("entries", [])) != 1
    ):
        raise CanaryPreflightReceiptError(
            "The position evidence chain changed after preflight."
        )
    chain_sha256 = str(chain.get("chainSha256", ""))
    if not _HEX_SHA256.fullmatch(chain_sha256):
        raise CanaryPreflightReceiptError(
            "The validated position evidence chain hash is invalid."
        )
    expires_at = normalized_preflight_at + timedelta(
        seconds=receipt_policy.decision_window_seconds
    )
    if normalized_recorded_at < normalized_preflight_at:
        raise CanaryPreflightReceiptError(
            "A preflight receipt cannot be recorded before evaluation."
        )
    if normalized_recorded_at > expires_at:
        raise CanaryPreflightReceiptError(
            "The preflight expired before its receipt could be recorded."
        )
    receipt = CanaryPreflightReceipt(
        recorded_at=normalized_recorded_at.isoformat(),
        expires_at=expires_at.isoformat(),
        decision_window_seconds=receipt_policy.decision_window_seconds,
        position_chain_sha256=chain_sha256,
        position_result=position_result,
        funding_result=funding_result,
        order_result=order_result,
        stop_result=stop_result,
        preflight_result=preflight_result,
    )
    _validate_receipt_payload(receipt.to_dict())
    return receipt


def inspect_canary_preflight_receipt(
    *,
    store: CanaryPreflightReceiptStore,
    position_evidence_store: CanaryPositionEvidenceStore,
    observed_at: datetime,
    policy: CanaryPreflightReceiptPolicy,
) -> CanaryPreflightReceiptInspection:
    """Inspect receipt integrity and expiry without creating execution authority."""

    normalized_observed_at = _require_aware_datetime(
        observed_at,
        field="observed_at",
    )
    payload = store.load()
    if payload is None:
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_MISSING,
            conclusion="CANARY_PREFLIGHT_RECEIPT_MISSING",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=None,
            expires_at=None,
            findings=("No immutable canary preflight receipt exists.",),
        )
    try:
        position_chain = position_evidence_store.load()
    except (CanaryPositionEvidenceError, OSError) as exc:
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_BLOCKED,
            conclusion="CANARY_PREFLIGHT_SOURCE_EVIDENCE_INVALID",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=str(payload["receiptId"]),
            expires_at=str(payload["expiresAt"]),
            findings=(
                "Current position evidence could not be independently revalidated: "
                f"{exc}",
            ),
        )
    if (
        position_chain.get("chainState") != PRE_CANARY_VERIFIED
        or position_chain.get("chainSha256")
        != payload.get("positionChainSha256")
    ):
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_BLOCKED,
            conclusion="CANARY_PREFLIGHT_SOURCE_EVIDENCE_CHANGED",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=str(payload["receiptId"]),
            expires_at=str(payload["expiresAt"]),
            findings=(
                "Current position evidence no longer matches the receipt.",
            ),
        )
    if payload.get("decisionWindowSeconds") != policy.decision_window_seconds:
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_BLOCKED,
            conclusion="CANARY_PREFLIGHT_RECEIPT_POLICY_MISMATCH",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=str(payload["receiptId"]),
            expires_at=str(payload["expiresAt"]),
            findings=("Receipt decision window does not match frozen policy.",),
        )
    recorded_at = _parse_timestamp(payload["recordedAt"], field="recordedAt")
    expires_at = _parse_timestamp(payload["expiresAt"], field="expiresAt")
    if (
        normalized_observed_at
        < recorded_at - timedelta(seconds=policy.max_future_skew_seconds)
    ):
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_BLOCKED,
            conclusion="CANARY_PREFLIGHT_RECEIPT_CLOCK_INVALID",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=str(payload["receiptId"]),
            expires_at=expires_at.isoformat(),
            findings=("Receipt observation time predates the receipt.",),
        )
    if normalized_observed_at > expires_at:
        return CanaryPreflightReceiptInspection(
            status=RECEIPT_EXPIRED,
            conclusion="CANARY_PREFLIGHT_RECEIPT_EXPIRED",
            observed_at=normalized_observed_at.isoformat(),
            receipt_id=str(payload["receiptId"]),
            expires_at=expires_at.isoformat(),
            findings=("The manual-decision window has expired.",),
        )
    return CanaryPreflightReceiptInspection(
        status=RECEIPT_AWAITING_DECISION,
        conclusion="CANARY_PREFLIGHT_RECEIPT_AWAITS_STEVEN_DECISION",
        observed_at=normalized_observed_at.isoformat(),
        receipt_id=str(payload["receiptId"]),
        expires_at=expires_at.isoformat(),
        findings=(),
    )


def _validate_receipt_payload(payload: dict[str, object]) -> None:
    if set(payload) != _RECEIPT_KEYS:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt fields do not match the frozen schema."
        )
    if payload.get("schemaVersion") != CANARY_PREFLIGHT_RECEIPT_SCHEMA_VERSION:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt schema is unsupported."
        )
    if (
        payload.get("oneWay") is not True
        or payload.get("replaceSupported") is not False
        or payload.get("clearSupported") is not False
        or payload.get("manualDecisionRequired") is not True
        or payload.get("executionPermit") is not False
        or payload.get("realOrderApproval") is not False
        or payload.get("retryAllowed") is not False
        or payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt safety flags are invalid."
        )
    decision_window = payload.get("decisionWindowSeconds")
    CanaryPreflightReceiptPolicy(decision_window_seconds=decision_window)
    recorded_at = _parse_timestamp(payload.get("recordedAt"), field="recordedAt")
    expires_at = _parse_timestamp(payload.get("expiresAt"), field="expiresAt")
    chain_sha256 = str(payload.get("positionChainSha256", ""))
    if not _HEX_SHA256.fullmatch(chain_sha256):
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt chain hash is invalid."
        )
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt evidence set is malformed."
        )
    for value in evidence.values():
        if not isinstance(value, dict):
            raise CanaryPreflightReceiptError(
                "Canary preflight receipt evidence payload is malformed."
            )
    _validate_evidence_semantics(evidence)
    preflight_at = _parse_timestamp(
        evidence["preflight"].get("evaluatedAt"),
        field="preflight evaluatedAt",
    )
    if recorded_at < preflight_at:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt predates its evaluation."
        )
    expected_expiry = preflight_at + timedelta(seconds=float(decision_window))
    if expires_at != expected_expiry or recorded_at > expires_at:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt expiry chronology is invalid."
        )
    expected_evidence_hash = _sha256_payload(
        {
            "positionChainSha256": chain_sha256,
            "evidence": evidence,
        }
    )
    if payload.get("evidenceSetSha256") != expected_evidence_hash:
        raise CanaryPreflightReceiptError(
            "Canary preflight evidence-set hash changed."
        )
    expected_receipt_id = (
        f"canary-preflight-receipt-{expected_evidence_hash[:24]}"
    )
    if payload.get("receiptId") != expected_receipt_id:
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt identity changed."
        )
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "receiptSha256"
    }
    if payload.get("receiptSha256") != _sha256_payload(unsigned):
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt hash changed."
        )


def _validate_evidence_semantics(evidence: dict[str, dict[str, object]]) -> None:
    position = evidence["positionInvariant"]
    funding = evidence["fundingGate"]
    order = evidence["orderReconciliation"]
    stop = evidence["independentStopDrill"]
    preflight = evidence["preflight"]
    expected_schemas = (
        (position, POSITION_INVARIANT_SCHEMA_VERSION),
        (funding, CANARY_FUNDING_SCHEMA_VERSION),
        (order, CANARY_ORDER_RECONCILIATION_SCHEMA_VERSION),
        (stop, CANARY_STOP_SCHEMA_VERSION),
        (preflight, CANARY_PREFLIGHT_SCHEMA_VERSION),
    )
    if any(item.get("schemaVersion") != schema for item, schema in expected_schemas):
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt contains an unsupported evidence schema."
        )
    if (
        position.get("status") != "PASS"
        or position.get("phase") != "PRE_CANARY"
        or position.get("findings") != []
    ):
        raise CanaryPreflightReceiptError(
            "Receipt position evidence is not a clean PRE_CANARY result."
        )
    if (
        funding.get("status") != "PASS"
        or funding.get("settledCashAvailable") is not True
        or funding.get("settledCashSufficient") is not True
        or funding.get("restrictionState") != RESTRICTIONS_CLEAR
        or funding.get("restrictionCodes") != []
        or funding.get("findings") != []
    ):
        raise CanaryPreflightReceiptError(
            "Receipt funding evidence is not a clean settled-cash result."
        )
    if (
        order.get("status") != "BLOCK"
        or order.get("conclusion") != NO_PRIOR_SUBMISSION_EVIDENCE
        or order.get("attemptRecorded") is not False
        or order.get("exactMatchCount") != 0
        or order.get("providerOrderId") is not None
        or order.get("brokerStatus") is not None
        or order.get("findings") != []
        or order.get("retryAllowed") is not False
    ):
        raise CanaryPreflightReceiptError(
            "Receipt order evidence does not prove a clean pre-submit state."
        )
    if (
        stop.get("status") != "PASS"
        or stop.get("conclusion") != "INDEPENDENT_STOP_DRILL_PROVEN"
        or stop.get("processRunning") is not False
        or stop.get("credentialState") != CREDENTIAL_REVOKED
        or stop.get("findings") != []
    ):
        raise CanaryPreflightReceiptError(
            "Receipt stop evidence is not a clean independent drill result."
        )
    if (
        preflight.get("status") != PREFLIGHT_READY
        or preflight.get("conclusion") != PREFLIGHT_READY_CONCLUSION
        or preflight.get("findings") != []
        or preflight.get("readyForManualDecision") is not True
        or preflight.get("components")
        != {
            "positionInvariant": "PASS",
            "positionEvidenceChain": "PASS",
            "fundingGate": "PASS",
            "orderReconciliation": "PASS",
            "independentStopDrill": "PASS",
        }
    ):
        raise CanaryPreflightReceiptError(
            "Receipt preflight evidence is not awaiting Steven's decision."
        )
    for item in evidence.values():
        if (
            item.get("transmitting") is not False
            and item is not stop
        ) or item.get("orderTransmission") != "UNAVAILABLE":
            raise CanaryPreflightReceiptError(
                "Receipt evidence violates the nontransmitting boundary."
            )
    if (
        stop.get("executionPermit") is not False
        or stop.get("latchClearSupported") is not False
        or stop.get("credentialMutationPerformed") is not False
        or stop.get("processMutationPerformed") is not False
        or preflight.get("executionPermit") is not False
        or preflight.get("realOrderApproval") is not False
        or preflight.get("retryAllowed") is not False
        or preflight.get("manualDecisionRequired") is not True
    ):
        raise CanaryPreflightReceiptError(
            "Receipt evidence contains an authority-bearing safety flag."
        )
    cross_identity = (
        (
            position.get("accountEnding"),
            funding.get("accountEnding"),
            preflight.get("accountEnding"),
        ),
        (
            position.get("accountType"),
            funding.get("accountType"),
            preflight.get("accountType"),
        ),
        (
            position.get("canaryIntentId"),
            preflight.get("canaryIntentId"),
        ),
        (
            funding.get("requirementId"),
            preflight.get("fundingRequirementId"),
        ),
        (
            order.get("commandId"),
            preflight.get("orderCommandId"),
        ),
        (
            order.get("sequenceId"),
            preflight.get("sequenceId"),
        ),
        (
            stop.get("latchSha256"),
            preflight.get("stopLatchSha256"),
        ),
    )
    if any(len(set(values)) != 1 for values in cross_identity):
        raise CanaryPreflightReceiptError(
            "Canary preflight receipt evidence identities disagree."
        )


def _parse_timestamp(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryPreflightReceiptError(
            f"{field} must be a valid ISO-8601 timestamp."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryPreflightReceiptError(
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


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )
