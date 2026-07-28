from __future__ import annotations

"""Immutable local evidence chain for nontransmitting canary position checks."""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from momentum_hunter.schwab_canary_positions import (
    CANARY_ACTIVE,
    POST_CANARY,
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionInvariantResult,
    POSITION_INVARIANT_SCHEMA_VERSION,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    EXPECTED_ACCOUNT_TYPE,
    SchwabAccountBinding,
    normalize_last_four,
)


CANARY_POSITION_EVIDENCE_SCHEMA_VERSION = "SCHWAB_CANARY_POSITION_EVIDENCE_V1"
AWAITING_PRE_CANARY = "AWAITING_PRE_CANARY"
PRE_CANARY_VERIFIED = "PRE_CANARY_VERIFIED"
CANARY_ACTIVE_VERIFIED = "CANARY_ACTIVE_VERIFIED"
CANARY_SEQUENCE_COMPLETE = "CANARY_SEQUENCE_COMPLETE"

_EXPECTED_PHASE_BY_STATE = {
    AWAITING_PRE_CANARY: PRE_CANARY,
    PRE_CANARY_VERIFIED: CANARY_ACTIVE,
    CANARY_ACTIVE_VERIFIED: POST_CANARY,
}
_ADVANCED_STATE_BY_PHASE = {
    PRE_CANARY: PRE_CANARY_VERIFIED,
    CANARY_ACTIVE: CANARY_ACTIVE_VERIFIED,
    POST_CANARY: CANARY_SEQUENCE_COMPLETE,
}


class CanaryPositionEvidenceError(RuntimeError):
    pass


class CanaryPositionEvidenceStore:
    """Write-once hash-linked attempts for one exact canary intent."""

    def __init__(
        self,
        *,
        path: Path,
        sequence_id: str,
        binding: SchwabAccountBinding,
        intent: CanaryIntent,
    ) -> None:
        self.path = path.expanduser().resolve()
        self.sequence_id = _normalize_identifier(sequence_id, field="sequence ID")
        self.binding = binding
        self.intent = intent
        self._validate_binding()
        self.binding_commitment = _binding_commitment(
            sequence_id=self.sequence_id,
            binding=self.binding,
        )

    def load(self) -> dict[str, object]:
        if not self.path.is_file():
            raise CanaryPositionEvidenceError(
                "No canary position evidence chain exists."
            )
        payload = _load_json(self.path)
        self._validate_payload(payload)
        return _copy_payload(payload)

    def record(
        self,
        result: CanaryPositionInvariantResult,
        *,
        recorded_at: datetime,
    ) -> dict[str, object]:
        normalized_recorded_at = _require_aware_datetime(
            recorded_at,
            field="recorded_at",
        )
        result_payload = result.to_dict()
        self._validate_result_payload(result_payload)
        result_evaluated_at = _parse_aware_timestamp(
            str(result_payload["evaluatedAt"]),
            field="result evaluatedAt",
        )
        if normalized_recorded_at < result_evaluated_at:
            raise CanaryPositionEvidenceError(
                "A canary position result cannot be recorded before it was evaluated."
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.path):
            original_bytes = self.path.read_bytes() if self.path.is_file() else None
            if original_bytes is None:
                payload = self._new_payload()
            else:
                payload = _decode_json(original_bytes, path=self.path)
                self._validate_payload(payload)

            result_sha256 = _sha256_text(_canonical_json(result_payload))
            for entry in _require_entries(payload):
                if entry.get("resultSha256") == result_sha256:
                    if entry.get("result") != result_payload:
                        raise CanaryPositionEvidenceError(
                            "A canary evidence result hash collision was detected."
                        )
                    return _copy_payload(payload)

            state_before = str(payload["chainState"])
            if state_before == CANARY_SEQUENCE_COMPLETE:
                raise CanaryPositionEvidenceError(
                    "The canary position evidence sequence is already complete."
                )
            expected_phase = _EXPECTED_PHASE_BY_STATE[state_before]
            if result.phase != expected_phase:
                raise CanaryPositionEvidenceError(
                    f"The next canary position phase must be {expected_phase}; "
                    f"received {result.phase}."
                )
            entries = _require_entries(payload)
            if entries:
                last_evaluated_at = _parse_aware_timestamp(
                    str(entries[-1]["result"]["evaluatedAt"]),
                    field="previous result evaluatedAt",
                )
                if result_evaluated_at < last_evaluated_at:
                    raise CanaryPositionEvidenceError(
                        "Canary position results must be recorded in evaluation order."
                    )
                last_recorded_at = _parse_aware_timestamp(
                    str(entries[-1]["recordedAt"]),
                    field="previous entry recordedAt",
                )
                if normalized_recorded_at < last_recorded_at:
                    raise CanaryPositionEvidenceError(
                        "Canary position evidence recording time cannot move backward."
                    )

            state_after = (
                _ADVANCED_STATE_BY_PHASE[result.phase]
                if result.status == "PASS"
                else state_before
            )
            previous_entry_sha256 = (
                str(entries[-1]["entrySha256"]) if entries else ""
            )
            entry_without_hash: dict[str, object] = {
                "entryNumber": len(entries) + 1,
                "recordedAt": normalized_recorded_at.isoformat(),
                "stateBefore": state_before,
                "stateAfter": state_after,
                "previousEntrySha256": previous_entry_sha256,
                "resultSha256": result_sha256,
                "result": result_payload,
            }
            entry = {
                **entry_without_hash,
                "entrySha256": _sha256_text(_canonical_json(entry_without_hash)),
            }
            entries.append(entry)
            if not payload["createdAt"]:
                payload["createdAt"] = normalized_recorded_at.isoformat()
            payload["updatedAt"] = normalized_recorded_at.isoformat()
            payload["chainState"] = state_after
            payload["chainSha256"] = _payload_sha256(payload)

            encoded = (_canonical_json(payload) + "\n").encode("ascii")
            self._atomic_replace(
                encoded,
                expected_original=original_bytes,
            )
            return _copy_payload(payload)

    def _new_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": CANARY_POSITION_EVIDENCE_SCHEMA_VERSION,
            "sequenceId": self.sequence_id,
            "bindingCommitment": self.binding_commitment,
            "accountEnding": self.binding.account_number_last_four,
            "accountType": self.binding.account_type,
            "intent": {
                "intentId": self.intent.intent_id,
                "symbol": self.intent.symbol,
                "quantity": self.intent.quantity,
            },
            "createdAt": "",
            "updatedAt": "",
            "chainState": AWAITING_PRE_CANARY,
            "entries": [],
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
        payload["chainSha256"] = _payload_sha256(payload)
        return payload

    def _validate_binding(self) -> None:
        if not self.binding.account_hash.strip():
            raise CanaryPositionEvidenceError(
                "A canary evidence chain requires the pinned account binding."
            )
        try:
            normalize_last_four(self.binding.account_number_last_four)
        except AccountIsolationError as exc:
            raise CanaryPositionEvidenceError(
                "The pinned account ending is invalid."
            ) from exc
        if self.binding.account_type != EXPECTED_ACCOUNT_TYPE:
            raise CanaryPositionEvidenceError(
                f"The canary evidence chain requires {EXPECTED_ACCOUNT_TYPE}."
            )

    def _validate_result_payload(self, payload: dict[str, object]) -> None:
        if payload.get("schemaVersion") != POSITION_INVARIANT_SCHEMA_VERSION:
            raise CanaryPositionEvidenceError(
                "The canary position result schema is unsupported."
            )
        if payload.get("accountEnding") != self.binding.account_number_last_four:
            raise CanaryPositionEvidenceError(
                "The canary position result account ending changed."
            )
        if payload.get("accountType") != self.binding.account_type:
            raise CanaryPositionEvidenceError(
                "The canary position result account type changed."
            )
        if payload.get("canaryIntentId") != self.intent.intent_id:
            raise CanaryPositionEvidenceError(
                "The canary position result intent ID changed."
            )
        if payload.get("canarySymbol") != self.intent.symbol:
            raise CanaryPositionEvidenceError(
                "The canary position result symbol changed."
            )
        if payload.get("expectedQuantity") != self.intent.quantity:
            raise CanaryPositionEvidenceError(
                "The canary position result quantity changed."
            )
        if payload.get("transmitting") is not False:
            raise CanaryPositionEvidenceError(
                "A transmitting result cannot enter canary position evidence."
            )
        if payload.get("orderTransmission") != "UNAVAILABLE":
            raise CanaryPositionEvidenceError(
                "Order transmission must remain unavailable."
            )
        findings = payload.get("findings")
        if not isinstance(findings, list):
            raise CanaryPositionEvidenceError(
                "The canary position result findings are malformed."
            )
        if payload.get("status") == "PASS":
            if findings or payload.get("conclusion") != "POSITION_INVARIANT_PASS":
                raise CanaryPositionEvidenceError(
                    "A passing canary position result has contradictory findings."
                )
        elif payload.get("status") == "BLOCK":
            if not findings or payload.get("conclusion") != "POSITION_INVARIANT_BLOCK":
                raise CanaryPositionEvidenceError(
                    "A blocked canary position result requires findings."
                )
        else:
            raise CanaryPositionEvidenceError(
                "The canary position result status is unsupported."
            )

    def _validate_payload(self, payload: dict[str, object]) -> None:
        if payload.get("schemaVersion") != CANARY_POSITION_EVIDENCE_SCHEMA_VERSION:
            raise CanaryPositionEvidenceError(
                "The canary position evidence schema is unsupported."
            )
        expected_identity = {
            "sequenceId": self.sequence_id,
            "bindingCommitment": self.binding_commitment,
            "accountEnding": self.binding.account_number_last_four,
            "accountType": self.binding.account_type,
            "intent": {
                "intentId": self.intent.intent_id,
                "symbol": self.intent.symbol,
                "quantity": self.intent.quantity,
            },
        }
        for key, expected in expected_identity.items():
            if payload.get(key) != expected:
                raise CanaryPositionEvidenceError(
                    f"The canary position evidence {key} does not match this sequence."
                )
        if payload.get("transmitting") is not False:
            raise CanaryPositionEvidenceError(
                "Canary position evidence cannot be transmitting."
            )
        if payload.get("orderTransmission") != "UNAVAILABLE":
            raise CanaryPositionEvidenceError(
                "Canary position evidence must keep order transmission unavailable."
            )
        entries = _require_entries(payload)
        state = AWAITING_PRE_CANARY
        previous_entry_sha256 = ""
        previous_evaluated_at: datetime | None = None
        previous_recorded_at: datetime | None = None
        first_recorded_at = ""
        last_recorded_at = ""
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise CanaryPositionEvidenceError(
                    "A canary position evidence entry is malformed."
                )
            result = entry.get("result")
            if not isinstance(result, dict):
                raise CanaryPositionEvidenceError(
                    "A canary position evidence result is malformed."
                )
            self._validate_result_payload(result)
            if entry.get("entryNumber") != index:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence entry numbering changed."
                )
            if entry.get("stateBefore") != state:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence state continuity changed."
                )
            if entry.get("previousEntrySha256") != previous_entry_sha256:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence hash linkage changed."
                )
            expected_phase = _EXPECTED_PHASE_BY_STATE.get(state)
            if expected_phase is None or result.get("phase") != expected_phase:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence phase ordering changed."
                )
            result_sha256 = _sha256_text(_canonical_json(result))
            if entry.get("resultSha256") != result_sha256:
                raise CanaryPositionEvidenceError(
                    "A canary position evidence result hash changed."
                )
            entry_without_hash = {
                key: value
                for key, value in entry.items()
                if key != "entrySha256"
            }
            expected_entry_sha256 = _sha256_text(
                _canonical_json(entry_without_hash)
            )
            if entry.get("entrySha256") != expected_entry_sha256:
                raise CanaryPositionEvidenceError(
                    "A canary position evidence entry hash changed."
                )
            evaluated_at = _parse_aware_timestamp(
                str(result.get("evaluatedAt", "")),
                field="stored result evaluatedAt",
            )
            recorded_at = _parse_aware_timestamp(
                str(entry.get("recordedAt", "")),
                field="stored entry recordedAt",
            )
            if recorded_at < evaluated_at:
                raise CanaryPositionEvidenceError(
                    "Stored canary evidence predates its evaluation."
                )
            if previous_evaluated_at is not None and evaluated_at < previous_evaluated_at:
                raise CanaryPositionEvidenceError(
                    "Stored canary evidence evaluation order changed."
                )
            if previous_recorded_at is not None and recorded_at < previous_recorded_at:
                raise CanaryPositionEvidenceError(
                    "Stored canary evidence recording order changed."
                )
            expected_state_after = (
                _ADVANCED_STATE_BY_PHASE[str(result["phase"])]
                if result.get("status") == "PASS"
                else state
            )
            if entry.get("stateAfter") != expected_state_after:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence advancement changed."
                )
            if index == 1:
                first_recorded_at = recorded_at.isoformat()
            last_recorded_at = recorded_at.isoformat()
            state = expected_state_after
            previous_entry_sha256 = expected_entry_sha256
            previous_evaluated_at = evaluated_at
            previous_recorded_at = recorded_at

        if payload.get("chainState") != state:
            raise CanaryPositionEvidenceError(
                "The canary position evidence chain state changed."
            )
        expected_created_at = first_recorded_at if entries else ""
        expected_updated_at = last_recorded_at if entries else ""
        if payload.get("createdAt") != expected_created_at:
            raise CanaryPositionEvidenceError(
                "The canary position evidence creation time changed."
            )
        if payload.get("updatedAt") != expected_updated_at:
            raise CanaryPositionEvidenceError(
                "The canary position evidence update time changed."
            )
        if payload.get("chainSha256") != _payload_sha256(payload):
            raise CanaryPositionEvidenceError(
                "The canary position evidence chain hash changed."
            )

    def _atomic_replace(
        self,
        encoded: bytes,
        *,
        expected_original: bytes | None,
    ) -> None:
        current = self.path.read_bytes() if self.path.is_file() else None
        if current != expected_original:
            raise CanaryPositionEvidenceError(
                "Canary position evidence changed concurrently."
            )
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            current = self.path.read_bytes() if self.path.is_file() else None
            if current != expected_original:
                raise CanaryPositionEvidenceError(
                    "Canary position evidence changed during persistence."
                )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


def _binding_commitment(
    *,
    sequence_id: str,
    binding: SchwabAccountBinding,
) -> str:
    payload = "|".join(
        (
            CANARY_POSITION_EVIDENCE_SCHEMA_VERSION,
            sequence_id,
            binding.account_hash,
            binding.account_number_last_four,
            binding.account_type,
        )
    )
    return _sha256_text(payload)


def _payload_sha256(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "chainSha256"
    }
    return _sha256_text(_canonical_json(unsigned))


def _require_entries(payload: dict[str, object]) -> list[dict[str, object]]:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise CanaryPositionEvidenceError(
            "The canary position evidence entries are malformed."
        )
    return entries


def _load_json(path: Path) -> dict[str, object]:
    return _decode_json(path.read_bytes(), path=path)


def _decode_json(payload: bytes, *, path: Path) -> dict[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryPositionEvidenceError(
            f"Canary position evidence is not valid JSON: {path.name}."
        ) from exc
    if not isinstance(decoded, dict):
        raise CanaryPositionEvidenceError(
            "Canary position evidence must be a JSON object."
        )
    return decoded


def _copy_payload(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(_canonical_json(payload))


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or not normalized.isascii()
        or not normalized.replace("-", "").replace("_", "").isalnum()
    ):
        raise CanaryPositionEvidenceError(
            f"A simple ASCII {field} is required."
        )
    return normalized


def _parse_aware_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise CanaryPositionEvidenceError(
            f"{field} must be valid ISO 8601."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanaryPositionEvidenceError(
            f"{field} must include a UTC offset."
        )
    return parsed


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise CanaryPositionEvidenceError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryPositionEvidenceError(
            f"{field} must include a UTC offset."
        )
    return value


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_token = uuid4().hex
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except FileExistsError as exc:
        raise CanaryPositionEvidenceError(
            "Canary position evidence is locked by another writer."
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(f"{os.getpid()}:{lock_token}")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            owner = lock_path.read_text(encoding="ascii")
        except FileNotFoundError:
            owner = ""
        if owner == f"{os.getpid()}:{lock_token}":
            lock_path.unlink()
