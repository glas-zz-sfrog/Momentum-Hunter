from __future__ import annotations

"""Fixed prospective identity for the Alpaca premarket fidelity retry."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from momentum_hunter.session_fidelity import (
    Checkpoint,
    SessionFidelityError,
    fingerprint,
    require_sanitized,
)


TASK_ID = "SESSION-FIDELITY-003"
SOURCE_TASK_ID = "SESSION-FIDELITY-001"
SCHEMA_VERSION = 1
CENTRAL = ZoneInfo("America/Chicago")
MAX_START_DELAY = timedelta(minutes=6)


def _central(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 12, hour, minute, tzinfo=CENTRAL)


CHECKPOINTS: dict[str, Checkpoint] = {
    "A": Checkpoint("A", "EARLY_PREMARKET_RETRY", _central(3, 5), 300, False, True),
    "B": Checkpoint("B", "PRE_SCHWAB_BOUNDARY_RETRY", _central(5, 55), 300, False, True),
    "C": Checkpoint("C", "SCHWAB_PREMARKET_RETRY", _central(6, 5), 300, False, True),
}


class PremarketRetryError(RuntimeError):
    """Raised when a prospective retry cannot run exactly as frozen."""


def get_checkpoint(code: str) -> Checkpoint:
    normalized = str(code).strip().upper()
    try:
        return CHECKPOINTS[normalized]
    except KeyError as exc:
        raise PremarketRetryError("Unknown premarket retry checkpoint.") from exc


def require_checkpoint_start(code: str, observed_at: datetime) -> Checkpoint:
    checkpoint = get_checkpoint(code)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise PremarketRetryError("Premarket retry clock must include a UTC offset.")
    observed = observed_at.astimezone(CENTRAL)
    if not checkpoint.target_central <= observed <= checkpoint.target_central + MAX_START_DELAY:
        raise PremarketRetryError(
            f"Checkpoint {checkpoint.code} must start in its bounded Central-time window."
        )
    return checkpoint


def program_context(code: str) -> Mapping[str, object]:
    checkpoint = get_checkpoint(code)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "retryTaskId": TASK_ID,
        "sourceTaskId": SOURCE_TASK_ID,
        "sourceCheckpoint": checkpoint.code,
        "sourceAttemptClassification": "FAILED_SAFE_PROVIDER_ADAPTER",
        "sourceEvidenceMutationAuthorized": False,
        "providerScope": "ALPACA_ONLY",
        "historicalSchwabEvidenceReused": False,
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
    }


def load_existing_retry(path: Path, *, checkpoint_code: str) -> dict[str, object]:
    try:
        result = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PremarketRetryError("Existing retry evidence could not be verified.") from exc
    if not isinstance(result, dict):
        raise PremarketRetryError("Existing retry evidence has the wrong document shape.")
    if result.get("evidenceFingerprint") != fingerprint(result):
        raise PremarketRetryError("Existing retry evidence fingerprint did not verify.")
    try:
        require_sanitized(result, forbidden_values=())
    except SessionFidelityError as exc:
        raise PremarketRetryError("Existing retry evidence failed sanitation.") from exc
    checkpoint = get_checkpoint(checkpoint_code)
    evidence = result.get("checkpoint")
    context = result.get("programContext")
    if result.get("taskId") != TASK_ID:
        raise PremarketRetryError("Existing retry evidence has the wrong task identity.")
    if result.get("mode") != "READ_ONLY_NONPERSISTING_SESSION_FIDELITY":
        raise PremarketRetryError("Existing retry evidence has the wrong operating mode.")
    if result.get("provider") != "ALPACA":
        raise PremarketRetryError("Existing retry evidence has the wrong provider identity.")
    if result.get("symbols") != ["SPY", "QQQ", "NVDA"]:
        raise PremarketRetryError("Existing retry evidence has the wrong symbol scope.")
    if not isinstance(evidence, Mapping) or evidence.get("code") != checkpoint.code:
        raise PremarketRetryError("Existing retry evidence has the wrong checkpoint identity.")
    if evidence.get("targetCentral") != checkpoint.target_central.isoformat():
        raise PremarketRetryError("Existing retry evidence has the wrong checkpoint time.")
    if context != program_context(checkpoint.code):
        raise PremarketRetryError("Existing retry evidence has the wrong program context.")
    for field in (
        "accountRequested",
        "accountValuesIncluded",
        "positionsRequested",
        "ordersRequested",
        "previewsRequested",
        "mutatingRequestAttempted",
        "strategyAuthorityGranted",
        "executionAuthorityGranted",
        "productionPersistence",
        "credentialMaterialIncluded",
        "liveEndpointReachable",
    ):
        if result.get(field) is not False:
            raise PremarketRetryError(f"Existing retry evidence violates {field}.")
    if result.get("orderTransmission") != "UNAVAILABLE":
        raise PremarketRetryError("Existing retry evidence has unsafe transmission authority.")
    return result
