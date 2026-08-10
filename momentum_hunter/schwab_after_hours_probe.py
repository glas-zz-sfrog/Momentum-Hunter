from __future__ import annotations

"""Unattended, read-only proof of Schwab after-hours candle behavior."""

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.schwab_candle_contract import EASTERN_TZ
from momentum_hunter.schwab_candle_observer import (
    CandleObservationOptions,
    GuardedStreamerAccess,
    SchwabCandleAccessGuard,
    SchwabCandleMarketHoursObserver,
    SchwabCandleObserverError,
    write_proof_once,
)
from momentum_hunter.schwab_market_data import SchwabMarketDataTransport
from momentum_hunter.schwab_market_data import SchwabMarketDataError


PROBE_SCHEMA_VERSION = 1
PROBE_TYPE = "SCHWAB_AFTER_HOURS_CANDLE_PROOF"
PROBE_MODE = "READ_ONLY_NONPERSISTING_AFTER_HOURS"
EXPECTED_ACCOUNT_ENDING = "2573"
SYMBOLS = ("SPY", "QQQ", "NVDA")
MIN_DURATION_SECONDS = 300
MAX_DURATION_SECONDS = 900
DEFAULT_DURATION_SECONDS = 900
MAX_QUOTE_AGE_SECONDS = 120.0
MAX_CANDLE_AGE_SECONDS = 180.0
UTC = timezone.utc


class SchwabAfterHoursProbeError(RuntimeError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


class _PreauthorizedAccessGuard:
    def __init__(self, access: GuardedStreamerAccess) -> None:
        self._access = access

    def authorize(self, expected_account_ending: str) -> GuardedStreamerAccess:
        if expected_account_ending != self._access.account_ending:
            raise SchwabAfterHoursProbeError(
                "The preauthorized account did not match the pinned account ending."
            )
        return self._access


def require_after_hours_window(observed_at: datetime, expected_date: date) -> datetime:
    aware = _aware(observed_at)
    eastern = aware.astimezone(EASTERN_TZ)
    if eastern.date() != expected_date:
        raise SchwabAfterHoursProbeError(
            "The after-hours proof did not run on its expected market date."
        )
    if not is_market_open_day(expected_date):
        raise SchwabAfterHoursProbeError(
            "The after-hours proof requires a U.S. equity market day."
        )
    local_time = eastern.time().replace(tzinfo=None)
    if not time(16, 0) <= local_time < time(20, 0):
        raise SchwabAfterHoursProbeError(
            "The after-hours proof requires the 4:00 PM to 8:00 PM Eastern session."
        )
    return eastern


def build_quote_evidence(
    quotes: Mapping[str, object],
    *,
    receipt: datetime,
) -> dict[str, dict[str, object]]:
    received = _aware(receipt)
    result: dict[str, dict[str, object]] = {}
    for symbol in SYMBOLS:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        quote_at = _timestamp(str(getattr(quote, "provider_quote_timestamp")))
        bid_at = _timestamp(str(getattr(quote, "provider_bid_timestamp")))
        ask_at = _timestamp(str(getattr(quote, "provider_ask_timestamp")))
        result[symbol] = {
            "symbol": symbol,
            "provider": "SCHWAB",
            "source": str(getattr(quote, "source")),
            "providerQuoteTimestamp": quote_at.isoformat(),
            "providerBidTimestamp": bid_at.isoformat(),
            "providerAskTimestamp": ask_at.isoformat(),
            "localReceiptTimestamp": received.isoformat(),
            "quoteAgeSeconds": _age(quote_at, received),
            "bidAgeSeconds": _age(bid_at, received),
            "askAgeSeconds": _age(ask_at, received),
            "bid": getattr(quote, "bid"),
            "ask": getattr(quote, "ask"),
            "last": getattr(quote, "last"),
            "volume": getattr(quote, "volume"),
            "realtime": bool(getattr(quote, "realtime")),
            "securityStatus": str(getattr(quote, "security_status")),
        }
    return result


def adjudicate_after_hours_proof(proof: Mapping[str, object]) -> dict[str, object]:
    requested = tuple(str(value) for value in _list(proof, "requestedSymbols"))
    candles = [row for row in _list(proof, "candles") if isinstance(row, Mapping)]
    quotes = _mapping(proof, "afterHoursQuotes")
    reconciliation = _mapping(proof, "streamHistoryReconciliation")

    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, evidence: str) -> None:
        checks.append(
            {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}
        )

    check(
        "EXPECTED_SYMBOLS",
        requested == SYMBOLS,
        f"Requested symbols were {', '.join(requested) or 'none'}."
    )
    quote_symbols = set(quotes)
    fresh_quotes = {
        symbol
        for symbol, value in quotes.items()
        if isinstance(value, Mapping)
        and value.get("bid") is not None
        and value.get("ask") is not None
        and _nonnegative_number(value.get("quoteAgeSeconds")) <= MAX_QUOTE_AGE_SECONDS
        and _nonnegative_number(value.get("bidAgeSeconds")) <= MAX_QUOTE_AGE_SECONDS
        and _nonnegative_number(value.get("askAgeSeconds")) <= MAX_QUOTE_AGE_SECONDS
    }
    check(
        "FRESH_QUOTES",
        quote_symbols == set(SYMBOLS) and fresh_quotes == set(SYMBOLS),
        f"Fresh bid/ask evidence was present for {len(fresh_quotes)} of {len(SYMBOLS)} symbols."
    )

    candle_by_symbol = {
        str(row.get("symbol")): row
        for row in candles
        if row.get("status") == "PASS"
    }
    complete_symbols = {
        symbol
        for symbol, row in candle_by_symbol.items()
        if row.get("ohlcvComplete") is True
        and row.get("session") == "extended"
        and _nonnegative_number(row.get("ageAtEvaluationSeconds"))
        <= MAX_CANDLE_AGE_SECONDS
    }
    check(
        "FRESH_EXTENDED_HOURS_OHLCV",
        complete_symbols == set(SYMBOLS),
        f"Fresh extended-hours OHLCV was present for {len(complete_symbols)} of {len(SYMBOLS)} symbols."
    )
    check(
        "STREAM_COMPLETED",
        proof.get("streamStatus") == "PASS",
        f"Stream status was {proof.get('streamStatus', 'MISSING')}."
    )
    check(
        "PRICE_HISTORY_COMPLETED",
        proof.get("priceHistoryStatus") == "PASS",
        f"Price-history status was {proof.get('priceHistoryStatus', 'MISSING')}."
    )

    comparable = _integer(reconciliation.get("comparableMinuteCount"))
    rows = [row for row in _list(reconciliation, "rows") if isinstance(row, Mapping)]
    differences = [row for row in rows if row.get("status") == "CORRECTED_OR_DIFFERENT"]
    non_volume_differences = [
        row
        for row in differences
        if any(field != "volume" for field in _list(row, "changedFields"))
    ]
    check(
        "STREAM_HISTORY_COMPARABLE",
        comparable >= len(SYMBOLS),
        f"{comparable} stream minutes were comparable with price history."
    )
    check(
        "OHLC_RECONCILIATION",
        not non_volume_differences,
        (
            "No open/high/low/close differences were observed."
            if not non_volume_differences
            else f"{len(non_volume_differences)} comparable minutes differed in OHLC."
        ),
    )
    check(
        "READ_ONLY_BOUNDARY",
        proof.get("productionDataWritten") is False
        and proof.get("positionsRequested") is False
        and proof.get("ordersRequested") is False
        and proof.get("orderTransmission") == "UNAVAILABLE",
        "No production persistence, positions, orders, or transmission capability was used.",
    )

    failed = [row["name"] for row in checks if row["status"] == "FAIL"]
    if failed:
        classification = "SCHWAB_AFTER_HOURS_DATA_INSUFFICIENT"
    elif differences:
        classification = "SCHWAB_AFTER_HOURS_PROVEN_WITH_LIMITATIONS"
    else:
        classification = "SCHWAB_AFTER_HOURS_PROVEN"
    return {
        "classification": classification,
        "checks": checks,
        "failedChecks": failed,
        "volumeDifferenceCount": len(differences) - len(non_volume_differences),
        "nonVolumeDifferenceCount": len(non_volume_differences),
        "canonicalityGranted": False,
        "productionPersistenceAuthorized": False,
        "ordersAuthorized": False,
    }


class SchwabAfterHoursProbe:
    def __init__(
        self,
        *,
        access_guard: object | None = None,
        quote_transport: object | None = None,
        observer_factory: Callable[..., object] | None = None,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.access_guard = access_guard or SchwabCandleAccessGuard()
        self.quote_transport = quote_transport or SchwabMarketDataTransport()
        self.observer_factory = observer_factory or SchwabCandleMarketHoursObserver
        self.utc_clock = utc_clock or (lambda: datetime.now(UTC))

    def observe(
        self,
        *,
        expected_session_date: date,
        duration_seconds: int = DEFAULT_DURATION_SECONDS,
        attempt_label: str,
    ) -> dict[str, object]:
        if not MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS:
            raise SchwabAfterHoursProbeError(
                f"Duration must be {MIN_DURATION_SECONDS} to {MAX_DURATION_SECONDS} seconds."
            )
        label = attempt_label.strip().upper()
        if label not in {"OPEN", "LATE"}:
            raise SchwabAfterHoursProbeError("Attempt label must be OPEN or LATE.")
        started_at = _aware(self.utc_clock())
        eastern = require_after_hours_window(started_at, expected_session_date)
        access = self.access_guard.authorize(EXPECTED_ACCOUNT_ENDING)
        quote_batch = self.quote_transport.fetch_quotes_with_clock(
            access.access_token,
            SYMBOLS,
        )
        quote_receipt = _timestamp(
            str(quote_batch.clock_skew_proof["responseReceivedAt"])
        )
        quote_evidence = build_quote_evidence(quote_batch.quotes, receipt=quote_receipt)
        options = CandleObservationOptions.create(
            SYMBOLS,
            expected_account_ending=EXPECTED_ACCOUNT_ENDING,
            duration_seconds=duration_seconds,
            extended_hours=True,
        )
        observer = self.observer_factory(
            access_guard=_PreauthorizedAccessGuard(access),
            utc_clock=self.utc_clock,
        )
        proof = dict(observer.observe(options))
        completed_at = _aware(self.utc_clock())
        require_after_hours_window(completed_at, expected_session_date)
        base_fingerprint = proof.pop("proofFingerprint", None)
        proof.update(
            {
                "afterHoursProbeSchemaVersion": PROBE_SCHEMA_VERSION,
                "afterHoursProbeType": PROBE_TYPE,
                "afterHoursProbeMode": PROBE_MODE,
                "attemptLabel": label,
                "expectedSessionDate": expected_session_date.isoformat(),
                "observedSession": "AFTER_HOURS",
                "observedEasternStart": eastern.isoformat(),
                "observedEasternCompletion": completed_at.astimezone(EASTERN_TZ).isoformat(),
                "baseObserverProofFingerprint": base_fingerprint,
                "afterHoursImplementationIdentity": {
                    "moduleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
                },
                "afterHoursQuotes": quote_evidence,
                "quoteClockProof": dict(quote_batch.clock_skew_proof),
                "positionsRequested": False,
                "ordersRequested": False,
                "orderTransmission": "UNAVAILABLE",
                "canonicalityGranted": False,
            }
        )
        proof["afterHoursAdjudication"] = adjudicate_after_hours_proof(proof)
        proof["proofFingerprint"] = _fingerprint(proof)
        _require_sanitized(proof, forbidden_values=(access.access_token,))
        return proof


def load_existing_proof(path: Path) -> dict[str, object]:
    try:
        raw = path.expanduser().resolve().read_bytes()
        proof = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabAfterHoursProbeError(
            "The existing after-hours proof could not be verified."
        ) from exc
    if not isinstance(proof, dict) or proof.get("afterHoursProbeType") != PROBE_TYPE:
        raise SchwabAfterHoursProbeError(
            "The existing file was not an after-hours proof."
        )
    expected = str(proof.get("proofFingerprint", ""))
    if not expected or expected != _fingerprint(proof):
        raise SchwabAfterHoursProbeError(
            "The existing after-hours proof fingerprint did not verify."
        )
    _require_sanitized(proof, forbidden_values=())
    return proof


def _fingerprint(proof: Mapping[str, object]) -> str:
    payload = dict(proof)
    payload.pop("proofFingerprint", None)
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest().upper()


def _require_sanitized(
    proof: Mapping[str, object],
    *,
    forbidden_values: Sequence[str],
) -> None:
    rendered = json.dumps(proof, separators=(",", ":"), sort_keys=True)
    lowered = rendered.lower()
    forbidden_terms = (
        '"access_token"',
        '"refresh_token"',
        '"client_secret"',
        '"accountnumber"',
        '"account_hash"',
        '"hashvalue"',
    )
    if any(term in lowered for term in forbidden_terms) or any(
        value and value in rendered for value in forbidden_values
    ):
        raise SchwabAfterHoursProbeError(
            "The after-hours proof failed credential and account-identity sanitation."
        )


def _list(source: Mapping[str, object], key: str) -> list[object]:
    value = source.get(key)
    return list(value) if isinstance(value, list) else []


def _mapping(source: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = source.get(key)
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _nonnegative_number(value: object) -> float:
    if value is None or isinstance(value, bool):
        return float("inf")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("inf")
    return parsed if parsed >= 0 else float("inf")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchwabAfterHoursProbeError(
            "Schwab returned an invalid provider timestamp."
        ) from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabAfterHoursProbeError("The after-hours probe requires aware timestamps.")
    return value.astimezone(UTC)


def _age(provider_at: datetime, receipt: datetime) -> float:
    return round((_aware(receipt) - _aware(provider_at)).total_seconds(), 6)


def _parse_session_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SchwabAfterHoursProbeError(
            "Expected session date must use YYYY-MM-DD."
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Run or verify one read-only Schwab after-hours candle proof."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-session-date", required=True)
    parser.add_argument("--attempt-label", choices=("OPEN", "LATE"), required=True)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
    )
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        expected_date = _parse_session_date(args.expected_session_date)
        if args.verify_existing:
            proof = load_existing_proof(args.output)
        else:
            proof = SchwabAfterHoursProbe().observe(
                expected_session_date=expected_date,
                duration_seconds=args.duration_seconds,
                attempt_label=args.attempt_label,
            )
            write_proof_once(proof, args.output)
        adjudication = _mapping(proof, "afterHoursAdjudication")
        print(
            json.dumps(
                {
                    "classification": adjudication.get("classification"),
                    "expectedSessionDate": proof.get("expectedSessionDate"),
                    "attemptLabel": proof.get("attemptLabel"),
                    "output": str(args.output),
                    "proofFingerprint": proof.get("proofFingerprint"),
                    "positionsRequested": False,
                    "ordersRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        SchwabAfterHoursProbeError,
        SchwabCandleObserverError,
        SchwabMarketDataError,
    ):
        print(
            json.dumps(
                {
                    "classification": "SCHWAB_AFTER_HOURS_PROBE_FAILED_SAFE",
                    "credentialMaterialIncluded": False,
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
