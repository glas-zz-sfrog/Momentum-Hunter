from __future__ import annotations

"""Sanitized, read-only shape evidence for one pinned Schwab account response."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from typing import Callable, Mapping

from momentum_hunter.schwab_account_discovery import (
    SchwabAccountDiscoveryError,
    SchwabAccountNumbersTransport,
)
from momentum_hunter.schwab_account_validation import (
    SchwabAccountDetailsTransport,
    SchwabAccountValidationError,
    build_unpersisted_binding_candidate,
    parse_account_identity,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import AccountIsolationError


ACCOUNT_SHAPE_SCHEMA_VERSION = "SCHWAB_ACCOUNT_SHAPE_EVIDENCE_V1"
ACCOUNT_SHAPE_SOURCE = "SCHWAB_ACCOUNT_DETAILS_GET_READ_ONLY_V1"
ACCOUNT_SHAPE_CONFIRMATION = "INSPECT SCHWAB ACCOUNT SHAPE READ ONLY"
MAX_SHAPE_DEPTH = 12
MAX_SHAPE_NODES = 4_096
MAX_OBJECT_FIELDS = 512
MAX_FIELD_NAME_LENGTH = 128
MAX_DISTINCT_ARRAY_SHAPES = 16


class SchwabAccountShapeEvidenceError(RuntimeError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True, repr=False)
class SchwabAccountShapeEvidence:
    observed_at: str
    account_ending: str
    account_type: str
    shape_sha256: str
    shape_json: str

    def __repr__(self) -> str:
        return (
            "SchwabAccountShapeEvidence("
            f"observed_at={self.observed_at!r}, "
            f"account_ending={self.account_ending!r}, "
            f"account_type={self.account_type!r}, "
            f"shape_sha256={self.shape_sha256!r})"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": ACCOUNT_SHAPE_SCHEMA_VERSION,
            "mode": "SCHWAB_ACCOUNT_SHAPE_READ_ONLY",
            "observedAt": self.observed_at,
            "source": ACCOUNT_SHAPE_SOURCE,
            "requestSequence": [
                "GET_ACCOUNT_NUMBERS_ONLY",
                "GET_SINGLE_ACCOUNT_WITHOUT_POSITIONS",
            ],
            "authorizedAccountCount": 1,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "bindingRevalidated": True,
            "shapeSha256": self.shape_sha256,
            "payloadShape": json.loads(self.shape_json),
            "valuesRetained": False,
            "rawPayloadRetained": False,
            "rawPayloadHashRetained": False,
            "balanceValuesSuppressed": True,
            "positionsRequested": False,
            "positionsReceived": False,
            "ordersRequested": False,
            "marketDataRequested": False,
            "persistence": "NONE",
            "providerEvidence": True,
            "semanticFieldMapping": "UNAVAILABLE",
            "executionPermit": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


@dataclass
class _ShapeBudget:
    remaining_nodes: int = MAX_SHAPE_NODES

    def consume(self) -> None:
        self.remaining_nodes -= 1
        if self.remaining_nodes < 0:
            raise SchwabAccountShapeEvidenceError(
                "Schwab account response shape exceeded the node limit."
            )


class SchwabAccountShapeInspector:
    """Collect one value-free field/type tree through the pinned GET-only path."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        binding_store: EncryptedSchwabAccountBindingStore | None = None,
        discovery_transport: SchwabAccountNumbersTransport | None = None,
        details_transport: SchwabAccountDetailsTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.bindings = binding_store or EncryptedSchwabAccountBindingStore()
        self.discovery_transport = (
            discovery_transport or SchwabAccountNumbersTransport()
        )
        self.details_transport = details_transport or SchwabAccountDetailsTransport()
        self.clock = clock or _utc_now

    def inspect(self, *, confirmation: str) -> SchwabAccountShapeEvidence:
        if confirmation != ACCOUNT_SHAPE_CONFIRMATION:
            raise SchwabAccountShapeEvidenceError(
                "Schwab account shape inspection requires the exact confirmation phrase."
            )
        binding = self.bindings.load()
        tokens = self.secrets.load_tokens()
        if tokens.expired:
            raise SchwabAccountShapeEvidenceError(
                "The Schwab OAuth access token expired; use the guarded bound refresh first."
            )
        accounts = self.discovery_transport.discover(tokens.access_token)
        if len(accounts) != 1:
            raise AccountIsolationError(
                "Account shape inspection requires exactly one authorized Schwab account."
            )
        discovered = accounts[0]
        if discovered.account_hash != binding.account_hash:
            raise AccountIsolationError(
                "The authorized Schwab account hash changed; shape inspection stopped."
            )
        if discovered.account_number_last_four != binding.account_number_last_four:
            raise AccountIsolationError(
                "The authorized Schwab account ending changed; shape inspection stopped."
            )
        payload = self.details_transport.fetch(
            tokens.access_token,
            discovered.account_hash,
        )
        identity = parse_account_identity(payload, discovered)
        if identity.account_type != "CASH":
            raise AccountIsolationError(
                "The authorized Schwab account is no longer a CASH account; "
                "shape inspection stopped."
            )
        candidate = build_unpersisted_binding_candidate(identity)
        if candidate != binding:
            raise AccountIsolationError(
                "The authorized Schwab CASH identity changed; shape inspection stopped."
            )
        observed_at = _require_aware_datetime(self.clock())
        shape = describe_json_shape(payload)
        shape_json = canonical_shape_json(shape)
        return SchwabAccountShapeEvidence(
            observed_at=observed_at.isoformat(),
            account_ending=binding.account_number_last_four,
            account_type=identity.account_type,
            shape_sha256=sha256(shape_json.encode("ascii")).hexdigest(),
            shape_json=shape_json,
        )

    def status(self) -> dict[str, object]:
        auth_status = self.secrets.status()
        binding_exists = self.bindings.exists
        account_ending = ""
        if binding_exists:
            account_ending = self.bindings.load().account_number_last_four
        return {
            "credentialsStored": auth_status["credentialsStored"],
            "oauthAuthorized": auth_status["oauthAuthorized"],
            "tokenState": auth_status["tokenState"],
            "accountBinding": "PINNED" if binding_exists else "NOT_BOUND",
            "accountEnding": account_ending,
            "shapeInspection": "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            "valuesRetained": False,
            "persistence": "NONE",
            "positionsRequested": False,
            "ordersRequested": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def describe_json_shape(value: object) -> dict[str, object]:
    budget = _ShapeBudget()
    return _describe_json_shape(value, budget=budget, depth=0)


def _describe_json_shape(
    value: object,
    *,
    budget: _ShapeBudget,
    depth: int,
) -> dict[str, object]:
    budget.consume()
    if depth > MAX_SHAPE_DEPTH:
        raise SchwabAccountShapeEvidenceError(
            "Schwab account response shape exceeded the depth limit."
        )
    if isinstance(value, Mapping):
        if len(value) > MAX_OBJECT_FIELDS:
            raise SchwabAccountShapeEvidenceError(
                "Schwab account response object exceeded the field limit."
            )
        fields: dict[str, object] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            if not isinstance(raw_key, str):
                raise SchwabAccountShapeEvidenceError(
                    "Schwab account response contained a non-string field name."
                )
            key = raw_key.strip()
            if (
                not key
                or key != raw_key
                or len(key) > MAX_FIELD_NAME_LENGTH
                or any(ord(character) < 32 for character in key)
            ):
                raise SchwabAccountShapeEvidenceError(
                    "Schwab account response contained an unsafe field name."
                )
            fields[key] = _describe_json_shape(
                value[raw_key],
                budget=budget,
                depth=depth + 1,
            )
        return {"type": "object", "fields": fields}
    if isinstance(value, list):
        distinct: dict[str, dict[str, object]] = {}
        for item in value:
            item_shape = _describe_json_shape(
                item,
                budget=budget,
                depth=depth + 1,
            )
            canonical = canonical_shape_json(item_shape)
            distinct.setdefault(canonical, item_shape)
            if len(distinct) > MAX_DISTINCT_ARRAY_SHAPES:
                raise SchwabAccountShapeEvidenceError(
                    "Schwab account response array exceeded the shape-variation limit."
                )
        return {
            "type": "array",
            "itemShapes": [distinct[key] for key in sorted(distinct)],
        }
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        if not isfinite(value):
            raise SchwabAccountShapeEvidenceError(
                "Schwab account response contained a non-finite number."
            )
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    raise SchwabAccountShapeEvidenceError(
        "Schwab account response contained an unsupported JSON value."
    )


def canonical_shape_json(shape: Mapping[str, object]) -> str:
    try:
        return json.dumps(
            shape,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SchwabAccountShapeEvidenceError(
            "Schwab account response shape was not canonical JSON."
        ) from exc


def _require_aware_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SchwabAccountShapeEvidenceError(
            "Schwab account shape observation time must be timezone-aware."
        )
    offset = value.utcoffset()
    if offset is None or not isfinite(offset.total_seconds()):
        raise SchwabAccountShapeEvidenceError(
            "Schwab account shape observation time must have a finite UTC offset."
        )
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Inspect the pinned Schwab account's value-free response shape."
    )
    parser.add_argument("command", choices=("status", "inspect"))
    args = parser.parse_args(argv)
    inspector = SchwabAccountShapeInspector()
    try:
        if args.command == "inspect":
            confirmation = input(
                f"Type {ACCOUNT_SHAPE_CONFIRMATION!r} to make two read-only "
                "account requests and retain only field names and JSON types: "
            )
            report = inspector.inspect(confirmation=confirmation).to_dict()
        else:
            report = inspector.status()
    except (
        AccountIsolationError,
        SchwabAccountDiscoveryError,
        SchwabAccountShapeEvidenceError,
        SchwabAccountValidationError,
        SchwabOAuthError,
    ) as exc:
        print(f"Schwab account shape inspection stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
