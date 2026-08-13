from __future__ import annotations

"""Read-only Schwab premarket authority checkpoints."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.schwab_candle_observer import (
    CandleObservationOptions,
    GuardedStreamerAccess,
    SchwabCandleAccessGuard,
    SchwabCandleMarketHoursObserver,
)
from momentum_hunter.schwab_market_data import SchwabMarketDataTransport
from momentum_hunter.session_fidelity import (
    EXPECTED_ACCOUNT_ENDING,
    SYMBOLS,
    _PinnedAccessGuard,
    adjudicate_schwab,
    build_quote_evidence,
    fingerprint,
    require_sanitized,
)


SCHEMA_VERSION = 1
TASK_ID = "SESSION-FIDELITY-008"
MODE = "READ_ONLY_NONPERSISTING_SCHWAB_PREMARKET_FIDELITY"
CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
MAX_START_DELAY = timedelta(minutes=6)
PROVIDER = "SCHWAB"


class SchwabPremarketFidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PremarketCheckpoint:
    code: str
    label: str
    target_central: datetime
    duration_seconds: int
    expected_state: str

    @property
    def target_eastern(self) -> datetime:
        return self.target_central.astimezone(EASTERN)

    def evidence(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "targetCentral": self.target_central.isoformat(),
            "targetEastern": self.target_eastern.isoformat(),
            "durationSeconds": self.duration_seconds,
            "providers": [PROVIDER],
            "providerScope": "SCHWAB_ONLY",
            "providerRole": "PREMARKET_QUOTE_AND_CANDLE_AUTHORITY_PROOF",
            "expectedState": self.expected_state,
        }


def checkpoints_for(session_date: date) -> dict[str, PremarketCheckpoint]:
    if not isinstance(session_date, date):
        raise SchwabPremarketFidelityError("Session date must be a calendar date.")
    return {
        "BOUNDARY": PremarketCheckpoint(
            "BOUNDARY",
            "SCHWAB_PREMARKET_BOUNDARY",
            datetime(
                session_date.year,
                session_date.month,
                session_date.day,
                5,
                55,
                tzinfo=CENTRAL,
            ),
            180,
            "PREMARKET_NOT_YET_ACTIVE_OR_TRANSITIONING",
        ),
        "ACTIVE": PremarketCheckpoint(
            "ACTIVE",
            "SCHWAB_PREMARKET_ACTIVE",
            datetime(
                session_date.year,
                session_date.month,
                session_date.day,
                6,
                5,
                tzinfo=CENTRAL,
            ),
            180,
            "PREMARKET_ACTIVE",
        ),
    }


def require_checkpoint_start(
    checkpoint: PremarketCheckpoint,
    observed_at: datetime,
) -> None:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise SchwabPremarketFidelityError("Checkpoint clock must include a UTC offset.")
    observed = observed_at.astimezone(CENTRAL)
    if not checkpoint.target_central <= observed <= checkpoint.target_central + MAX_START_DELAY:
        raise SchwabPremarketFidelityError(
            f"Checkpoint {checkpoint.code} must start in its bounded Central-time window."
        )


def run_checkpoint(
    checkpoint: PremarketCheckpoint,
    *,
    now: datetime | None = None,
    access_guard: object | None = None,
    quote_transport: object | None = None,
    observer_factory: Callable[..., object] | None = None,
    utc_clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    clock = utc_clock or (lambda: datetime.now(UTC))
    require_checkpoint_start(checkpoint, now or clock())
    guard = access_guard or SchwabCandleAccessGuard()
    access: GuardedStreamerAccess = guard.authorize(EXPECTED_ACCOUNT_ENDING)
    quote_client = quote_transport or SchwabMarketDataTransport()
    quote_batch = quote_client.fetch_quotes_with_clock(access.access_token, SYMBOLS)
    quote_evidence = build_quote_evidence(quote_batch)
    options = CandleObservationOptions.create(
        SYMBOLS,
        expected_account_ending=EXPECTED_ACCOUNT_ENDING,
        duration_seconds=checkpoint.duration_seconds,
        extended_hours=True,
    )
    observer = (observer_factory or SchwabCandleMarketHoursObserver)(
        access_guard=_PinnedAccessGuard(access),
        utc_clock=clock,
    )
    candle_observation = dict(observer.observe(options))
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "mode": MODE,
        "checkpoint": checkpoint.evidence(),
        "provider": PROVIDER,
        "symbols": list(SYMBOLS),
        "quotes": quote_evidence,
        "quoteClockProof": dict(quote_batch.clock_skew_proof),
        "candleObservation": candle_observation,
        "adjudication": adjudicate_schwab(candle_observation, quote_evidence),
        "productionPersistence": False,
        "accountValuesIncluded": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "previewsRequested": False,
        "orderTransmission": "UNAVAILABLE",
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
        "credentialMaterialIncluded": False,
    }
    result["evidenceFingerprint"] = fingerprint(result)
    require_sanitized(result, forbidden_values=(access.access_token,))
    return result


def write_json_once(value: Mapping[str, object], output: Path) -> str:
    target = output.expanduser().resolve()
    if target.exists():
        raise SchwabPremarketFidelityError("The write-once checkpoint already exists.")
    require_sanitized(value, forbidden_values=())
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def load_and_verify(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabPremarketFidelityError("Checkpoint evidence could not be verified.") from exc
    if not isinstance(value, dict) or value.get("taskId") != TASK_ID:
        raise SchwabPremarketFidelityError("The file has the wrong task identity.")
    if value.get("provider") != PROVIDER:
        raise SchwabPremarketFidelityError("The file has the wrong provider identity.")
    if value.get("evidenceFingerprint") != fingerprint(value):
        raise SchwabPremarketFidelityError("Checkpoint fingerprint did not verify.")
    checkpoint = value.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise SchwabPremarketFidelityError("Checkpoint identity is missing.")
    if checkpoint.get("providers") != [PROVIDER]:
        raise SchwabPremarketFidelityError("Checkpoint provider scope is contradictory.")
    require_sanitized(value, forbidden_values=())
    return value


def parse_session_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SchwabPremarketFidelityError("Session date must use YYYY-MM-DD.") from exc
