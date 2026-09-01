"""Authoritative lifecycle-to-TradePlan identity binding.

This module carries provenance only.  It deliberately contains no candidate,
risk, order, or execution-policy decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping


IDENTITY_SCHEMA_VERSION = 1
IDENTITY_AUTHORITY = "CONTINUOUS_TRADEPLAN_PRODUCER"
REPORT_IDENTITY_FIELD = "authoritative_lifecycle_identity"
IDENTITY_LINKAGE_PROVEN = "PROVEN"
IDENTITY_LINKAGE_UNKNOWN = "UNKNOWN"
IDENTITY_LINKAGE_NOT_AVAILABLE = "NOT_AVAILABLE"

_SHA256 = re.compile(r"[0-9a-f]{64}")


class LifecyclePositionIdentityError(ValueError):
    """Raised when an identity chain is incomplete or contradictory."""


@dataclass(frozen=True)
class AuthoritativeLifecycleTradePlanIdentity:
    schema_version: int
    authority: str
    opportunity_id: str
    setup_id: str
    trade_plan_id: str
    producer_record_id: str
    producer_record_fingerprint: str
    binding_fingerprint: str


def build_authoritative_lifecycle_identity(
    *,
    opportunity_id: str,
    setup_id: str,
    trade_plan_id: str,
    producer_record_id: str,
    producer_record_fingerprint: str,
) -> AuthoritativeLifecycleTradePlanIdentity:
    core = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "authority": IDENTITY_AUTHORITY,
        "opportunity_id": _require_sha256(opportunity_id, "Opportunity identity"),
        "setup_id": _require_sha256(setup_id, "Setup identity"),
        "trade_plan_id": _require_sha256(trade_plan_id, "TradePlan identity"),
        "producer_record_id": _require_text(
            producer_record_id, "Continuous Producer record identity"
        ),
        "producer_record_fingerprint": _require_sha256(
            producer_record_fingerprint, "Continuous Producer record fingerprint"
        ),
    }
    return AuthoritativeLifecycleTradePlanIdentity(
        **core,
        binding_fingerprint=_fingerprint(core),
    )


def lifecycle_identity_from_producer_record(
    record: Any,
) -> AuthoritativeLifecycleTradePlanIdentity:
    """Build the report-safe binding from a validated producer record."""

    return build_authoritative_lifecycle_identity(
        opportunity_id=str(getattr(record, "opportunity_id", "")),
        setup_id=str(getattr(record, "setup_id", "")),
        trade_plan_id=str(getattr(record, "trade_plan_id", "")),
        producer_record_id=str(getattr(record, "record_id", "")),
        producer_record_fingerprint=str(getattr(record, "fingerprint", "")),
    )


def lifecycle_identity_to_dict(
    identity: AuthoritativeLifecycleTradePlanIdentity,
) -> dict[str, Any]:
    validate_authoritative_lifecycle_identity(identity)
    return asdict(identity)


def bind_report_row_to_producer_identity(
    row: Mapping[str, Any],
    record: Any,
) -> dict[str, Any]:
    """Return a copy of a report row with explicit producer provenance.

    The row's embedded intraday plan must be the exact plan named by the
    producer record.  No symbol or timestamp is used to establish the join.
    """

    identity = lifecycle_identity_from_producer_record(record)
    expected_plan_id = report_row_intraday_plan_id(row)
    if expected_plan_id != identity.trade_plan_id:
        raise LifecyclePositionIdentityError(
            "Report TradePlan identity does not match the Continuous Producer binding."
        )
    bound = dict(row)
    bound[REPORT_IDENTITY_FIELD] = lifecycle_identity_to_dict(identity)
    return bound


def authoritative_lifecycle_identity_from_report_row(
    row: Mapping[str, Any],
) -> AuthoritativeLifecycleTradePlanIdentity:
    raw = row.get(REPORT_IDENTITY_FIELD)
    if not isinstance(raw, Mapping):
        raise LifecyclePositionIdentityError(
            "Authoritative lifecycle identity is missing from the persisted TradePlan row."
        )
    required = {
        "schema_version",
        "authority",
        "opportunity_id",
        "setup_id",
        "trade_plan_id",
        "producer_record_id",
        "producer_record_fingerprint",
        "binding_fingerprint",
    }
    if set(raw) != required:
        raise LifecyclePositionIdentityError(
            "Authoritative lifecycle identity has an unsupported shape."
        )
    try:
        identity = AuthoritativeLifecycleTradePlanIdentity(
            schema_version=int(raw["schema_version"]),
            authority=str(raw["authority"]),
            opportunity_id=str(raw["opportunity_id"]),
            setup_id=str(raw["setup_id"]),
            trade_plan_id=str(raw["trade_plan_id"]),
            producer_record_id=str(raw["producer_record_id"]),
            producer_record_fingerprint=str(raw["producer_record_fingerprint"]),
            binding_fingerprint=str(raw["binding_fingerprint"]),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise LifecyclePositionIdentityError(
            "Authoritative lifecycle identity is malformed."
        ) from exc
    validate_authoritative_lifecycle_identity(identity)
    embedded_plan_id = report_row_intraday_plan_id(row)
    if not embedded_plan_id or embedded_plan_id != identity.trade_plan_id:
        raise LifecyclePositionIdentityError(
            "Persisted TradePlan does not match its authoritative lifecycle binding."
        )
    return identity


def validate_authoritative_lifecycle_identity(
    identity: AuthoritativeLifecycleTradePlanIdentity,
) -> None:
    if (
        identity.schema_version != IDENTITY_SCHEMA_VERSION
        or identity.authority != IDENTITY_AUTHORITY
    ):
        raise LifecyclePositionIdentityError(
            "Authoritative lifecycle identity contract is unsupported."
        )
    _require_sha256(identity.opportunity_id, "Opportunity identity")
    _require_sha256(identity.setup_id, "Setup identity")
    _require_sha256(identity.trade_plan_id, "TradePlan identity")
    _require_text(identity.producer_record_id, "Continuous Producer record identity")
    _require_sha256(
        identity.producer_record_fingerprint,
        "Continuous Producer record fingerprint",
    )
    core = asdict(identity)
    supplied = core.pop("binding_fingerprint")
    if supplied != _fingerprint(core):
        raise LifecyclePositionIdentityError(
            "Authoritative lifecycle identity binding fingerprint did not verify."
        )


def report_row_intraday_plan_id(row: Mapping[str, Any]) -> str:
    trade_plan = row.get("trade_plan")
    if not isinstance(trade_plan, Mapping):
        return ""
    intraday = trade_plan.get("intraday_evidence")
    if not isinstance(intraday, Mapping):
        return ""
    value = str(intraday.get("plan_id", "")).strip().lower()
    return value if _SHA256.fullmatch(value) else ""


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise LifecyclePositionIdentityError(f"{label} must be a lowercase SHA-256.")
    return normalized


def _require_text(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > 256:
        raise LifecyclePositionIdentityError(f"{label} is missing or invalid.")
    return normalized


__all__ = [
    "AuthoritativeLifecycleTradePlanIdentity",
    "IDENTITY_AUTHORITY",
    "IDENTITY_LINKAGE_NOT_AVAILABLE",
    "IDENTITY_LINKAGE_PROVEN",
    "IDENTITY_LINKAGE_UNKNOWN",
    "IDENTITY_SCHEMA_VERSION",
    "LifecyclePositionIdentityError",
    "REPORT_IDENTITY_FIELD",
    "authoritative_lifecycle_identity_from_report_row",
    "bind_report_row_to_producer_identity",
    "build_authoritative_lifecycle_identity",
    "lifecycle_identity_from_producer_record",
    "lifecycle_identity_to_dict",
    "report_row_intraday_plan_id",
    "validate_authoritative_lifecycle_identity",
]
