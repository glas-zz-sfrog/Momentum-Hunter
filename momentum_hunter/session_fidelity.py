from __future__ import annotations

"""One-time, read-only market-session fidelity evidence."""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


SCHEMA_VERSION = 1
TASK_ID = "SESSION-FIDELITY-001"
EXPECTED_ACCOUNT_ENDING = "2573"
SYMBOLS = ("SPY", "QQQ", "NVDA")
CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
MAX_START_DELAY = timedelta(minutes=6)
QUOTE_FRESH_SECONDS = 120.0
CANDLE_FRESH_SECONDS = 180.0
CLASSIFICATIONS = {
    "HIGH_FIDELITY",
    "USEFUL_WITH_LIMITATIONS",
    "CONTEXT_ONLY",
    "STALE",
    "UNAVAILABLE",
}


class SessionFidelityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Checkpoint:
    code: str
    label: str
    target_central: datetime
    duration_seconds: int
    schwab: bool
    alpaca: bool
    externally_supplied: bool = False

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
            "providers": [
                provider
                for provider, enabled in (("SCHWAB", self.schwab), ("ALPACA", self.alpaca))
                if enabled
            ],
            "externallySupplied": self.externally_supplied,
        }


def _central(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=CENTRAL)


CHECKPOINTS: dict[str, Checkpoint] = {
    "A": Checkpoint("A", "EARLY_PREMARKET", _central(2026, 8, 11, 3, 5), 300, True, True),
    "B": Checkpoint("B", "PRE_SCHWAB_BOUNDARY", _central(2026, 8, 11, 5, 55), 300, True, True),
    "C": Checkpoint("C", "SCHWAB_PREMARKET", _central(2026, 8, 11, 6, 5), 300, True, True),
    "D": Checkpoint("D", "REGULAR_OPEN", _central(2026, 8, 10, 8, 35), 0, True, False, True),
    "E": Checkpoint("E", "REGULAR_STEADY_STATE", _central(2026, 8, 10, 12, 0), 180, True, False),
    "F": Checkpoint("F", "EARLY_AFTER_HOURS", _central(2026, 8, 10, 15, 5), 300, True, False),
    "G": Checkpoint("G", "LATE_AFTER_HOURS", _central(2026, 8, 10, 18, 55), 300, True, False),
    "H": Checkpoint("H", "TRUE_OVERNIGHT_TRANSITION", _central(2026, 8, 10, 19, 5), 300, True, True),
    "I": Checkpoint("I", "DEEP_OVERNIGHT", _central(2026, 8, 10, 22, 30), 300, True, True, True),
}


class _PinnedAccessGuard:
    def __init__(self, access: GuardedStreamerAccess) -> None:
        self._access = access

    def authorize(self, expected_account_ending: str) -> GuardedStreamerAccess:
        if expected_account_ending != self._access.account_ending:
            raise SessionFidelityError("The guarded Schwab account ending changed.")
        return self._access


def require_checkpoint_start(code: str, observed_at: datetime) -> Checkpoint:
    checkpoint = get_checkpoint(code)
    if checkpoint.externally_supplied:
        raise SessionFidelityError(
            f"Checkpoint {checkpoint.code} is supplied by an existing evidence lane."
        )
    observed = _aware(observed_at).astimezone(CENTRAL)
    if not checkpoint.target_central <= observed <= checkpoint.target_central + MAX_START_DELAY:
        raise SessionFidelityError(
            f"Checkpoint {checkpoint.code} must start in its bounded Central-time window."
        )
    return checkpoint


def get_checkpoint(code: str) -> Checkpoint:
    normalized = code.strip().upper()
    try:
        return CHECKPOINTS[normalized]
    except KeyError as exc:
        raise SessionFidelityError("Unknown session-fidelity checkpoint.") from exc


def build_quote_evidence(batch: object) -> dict[str, dict[str, object]]:
    clock_proof = getattr(batch, "clock_skew_proof")
    receipt = _timestamp(str(clock_proof["responseReceivedAt"]))
    quotes = getattr(batch, "quotes")
    result: dict[str, dict[str, object]] = {}
    for symbol in SYMBOLS:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        quote_at = _timestamp(str(quote.provider_quote_timestamp))
        bid_at = _timestamp(str(quote.provider_bid_timestamp))
        ask_at = _timestamp(str(quote.provider_ask_timestamp))
        result[symbol] = {
            "symbol": symbol,
            "source": str(quote.source),
            "providerQuoteTimestamp": quote_at.isoformat(),
            "providerBidTimestamp": bid_at.isoformat(),
            "providerAskTimestamp": ask_at.isoformat(),
            "localReceiptTimestamp": receipt.isoformat(),
            "quoteAgeSeconds": _age(quote_at, receipt),
            "bidAgeSeconds": _age(bid_at, receipt),
            "askAgeSeconds": _age(ask_at, receipt),
            "bid": quote.bid,
            "ask": quote.ask,
            "last": quote.last,
            "volume": quote.volume,
            "realtime": bool(quote.realtime),
            "securityStatus": str(quote.security_status),
        }
    return result


def adjudicate_schwab(
    stream_proof: Mapping[str, object],
    quotes: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    fresh_quotes = {
        symbol
        for symbol, row in quotes.items()
        if row.get("bid") is not None
        and row.get("ask") is not None
        and _number(row.get("quoteAgeSeconds")) <= QUOTE_FRESH_SECONDS
        and _number(row.get("bidAgeSeconds")) <= QUOTE_FRESH_SECONDS
        and _number(row.get("askAgeSeconds")) <= QUOTE_FRESH_SECONDS
    }
    candle_rows = [
        row for row in _list(stream_proof, "candles") if isinstance(row, Mapping)
    ]
    fresh_candles = {
        str(row.get("symbol"))
        for row in candle_rows
        if row.get("status") == "PASS"
        and row.get("ohlcvComplete") is True
        and _number(row.get("ageAtEvaluationSeconds")) <= CANDLE_FRESH_SECONDS
    }
    complete_volume = {
        str(row.get("symbol"))
        for row in candle_rows
        if row.get("status") == "PASS" and row.get("volume") is not None
    }
    expected = set(SYMBOLS)
    if fresh_quotes == expected and fresh_candles == expected:
        classification = "HIGH_FIDELITY"
    elif fresh_quotes or fresh_candles:
        classification = "USEFUL_WITH_LIMITATIONS"
    elif quotes or candle_rows:
        classification = "STALE"
    else:
        classification = "UNAVAILABLE"
    quote_authority = "SESSION_HIGH_FIDELITY" if fresh_quotes == expected else (
        "SESSION_LIMITED" if fresh_quotes else "NOT_PROVEN"
    )
    candle_authority = "SESSION_HIGH_FIDELITY" if fresh_candles == expected else (
        "SESSION_LIMITED" if fresh_candles else "NOT_PROVEN"
    )
    volume_authority = "SESSION_HIGH_FIDELITY" if complete_volume == expected else (
        "SESSION_LIMITED" if complete_volume else "NOT_PROVEN"
    )
    return {
        "classification": classification,
        "freshQuoteSymbols": sorted(fresh_quotes),
        "freshCandleSymbols": sorted(fresh_candles),
        "volumeSymbols": sorted(complete_volume),
        "QUOTE_AUTHORITY": quote_authority,
        "CANDLE_AUTHORITY": candle_authority,
        "VOLUME_AUTHORITY": volume_authority,
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
    }


def run_schwab_checkpoint(
    code: str,
    *,
    now: datetime | None = None,
    access_guard: object | None = None,
    quote_transport: object | None = None,
    observer_factory: Callable[..., object] | None = None,
    utc_clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    clock = utc_clock or (lambda: datetime.now(UTC))
    checkpoint = require_checkpoint_start(code, now or clock())
    if checkpoint.code == "H" or not checkpoint.schwab:
        raise SessionFidelityError(
            "The true-overnight checkpoint must use the frozen overnight probe."
        )
    guard = access_guard or SchwabCandleAccessGuard()
    access = guard.authorize(EXPECTED_ACCOUNT_ENDING)
    quote_client = quote_transport or SchwabMarketDataTransport()
    quote_batch = quote_client.fetch_quotes_with_clock(access.access_token, SYMBOLS)
    quote_evidence = build_quote_evidence(quote_batch)
    options = CandleObservationOptions.create(
        SYMBOLS,
        expected_account_ending=EXPECTED_ACCOUNT_ENDING,
        duration_seconds=checkpoint.duration_seconds,
        extended_hours=checkpoint.code != "E",
    )
    observer = (observer_factory or SchwabCandleMarketHoursObserver)(
        access_guard=_PinnedAccessGuard(access),
        utc_clock=clock,
    )
    stream_proof = dict(observer.observe(options))
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "mode": "READ_ONLY_NONPERSISTING_SESSION_FIDELITY",
        "checkpoint": checkpoint.evidence(),
        "provider": "SCHWAB",
        "symbols": list(SYMBOLS),
        "quotes": quote_evidence,
        "quoteClockProof": dict(quote_batch.clock_skew_proof),
        "candleObservation": stream_proof,
        "adjudication": adjudicate_schwab(stream_proof, quote_evidence),
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


def fingerprint(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("evidenceFingerprint", None)
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest().upper()


def write_json_once(value: Mapping[str, object], output: Path) -> str:
    target = output.expanduser().resolve()
    if target.exists():
        raise SessionFidelityError("The write-once session proof already exists.")
    require_sanitized(value, forbidden_values=())
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def load_and_verify(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionFidelityError("The session proof could not be verified.") from exc
    if not isinstance(value, dict) or value.get("taskId") != TASK_ID:
        raise SessionFidelityError("The file is not SESSION-FIDELITY-001 evidence.")
    if value.get("evidenceFingerprint") != fingerprint(value):
        raise SessionFidelityError("The session proof fingerprint did not verify.")
    require_sanitized(value, forbidden_values=())
    return value


def require_sanitized(
    value: Mapping[str, object], *, forbidden_values: Sequence[str]
) -> None:
    rendered = json.dumps(value, separators=(",", ":"), sort_keys=True)
    lowered = rendered.lower()
    forbidden_terms = (
        '"access_token"',
        '"refresh_token"',
        '"client_secret"',
        '"secret_key"',
        '"api_key"',
        '"accountnumber"',
        '"account_hash"',
        '"hashvalue"',
    )
    if any(term in lowered for term in forbidden_terms) or any(
        secret and secret in rendered for secret in forbidden_values
    ):
        raise SessionFidelityError("Session evidence failed sanitation.")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionFidelityError("Provider timestamp was invalid.") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionFidelityError("Session fidelity requires aware timestamps.")
    return value.astimezone(UTC)


def _age(provider_at: datetime, receipt: datetime) -> float:
    return round((_aware(receipt) - _aware(provider_at)).total_seconds(), 6)


def _number(value: object) -> float:
    if value is None or isinstance(value, bool):
        return float("inf")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("inf")
    return parsed if parsed >= 0 else float("inf")


def _list(source: Mapping[str, object], key: str) -> list[object]:
    value = source.get(key)
    return list(value) if isinstance(value, list) else []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded read-only Schwab session-fidelity checkpoint."
    )
    parser.add_argument("--checkpoint", choices=tuple("ABCEFG"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_existing:
            result = load_and_verify(args.output)
            proof_hash = hashlib.sha256(args.output.read_bytes()).hexdigest().upper()
        else:
            result = run_schwab_checkpoint(args.checkpoint)
            proof_hash = write_json_once(result, args.output)
        print(
            json.dumps(
                {
                    "checkpoint": args.checkpoint,
                    "classification": result["adjudication"]["classification"],
                    "output": str(args.output),
                    "sha256": proof_hash,
                    "ordersRequested": False,
                    "positionsRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "SESSION_FIDELITY_PROBE_FAILED_SAFE",
                    "credentialMaterialIncluded": False,
                    "errorType": type(exc).__name__,
                    "ordersRequested": False,
                    "positionsRequested": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
