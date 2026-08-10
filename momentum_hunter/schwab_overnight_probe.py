from __future__ import annotations

"""One-shot, read-only Schwab Sunday-night market-data fidelity probe."""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    MAX_PROOF_MESSAGES,
    SCHWAB_CHART_EQUITY_SERVICE,
    build_chart_equity_subscription,
    inspect_chart_equity_observations,
    parse_price_history_response,
)
from momentum_hunter.schwab_candle_observer import (
    ACK_TIMEOUT_SECONDS,
    SchwabCandleAccessGuard,
    SchwabCandleHttpTransport,
    SchwabCandleObserverError,
    SchwabCandleObserverNetworkError,
    SchwabCandleObserverResponseError,
    StreamConnection,
    StreamConnectionFactory,
    WebSocketClientFactory,
    build_streamer_login,
    parse_streamer_bootstrap,
    require_streamer_acknowledgement,
)
from momentum_hunter.schwab_market_data import SchwabMarketDataTransport


PROBE_SCHEMA = "SCHWAB_OVERNIGHT_FIDELITY_PROBE_V1"
PROBE_MODE = "READ_ONLY_SUNDAY_NIGHT_CONTEXT_RESEARCH"
SYMBOLS = ("SPY", "QQQ", "NVDA")
EXPECTED_ACCOUNT_ENDING = "2573"
MIN_DURATION_SECONDS = 300
MAX_DURATION_SECONDS = 600
DEFAULT_DURATION_SECONDS = 300
UTC = timezone.utc


class SchwabOvernightProbeError(RuntimeError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


class SchwabOvernightFidelityProbe:
    def __init__(
        self,
        *,
        access_guard: object | None = None,
        candle_http: object | None = None,
        quote_http: object | None = None,
        stream_factory: StreamConnectionFactory | None = None,
        utc_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.access_guard = access_guard or SchwabCandleAccessGuard()
        self.candle_http = candle_http or SchwabCandleHttpTransport()
        self.quote_http = quote_http or SchwabMarketDataTransport()
        self.stream_factory = stream_factory or WebSocketClientFactory()
        self.utc_clock = utc_clock or (lambda: datetime.now(UTC))
        self.monotonic_clock = monotonic_clock or time.monotonic

    def observe(
        self,
        *,
        duration_seconds: int = DEFAULT_DURATION_SECONDS,
    ) -> dict[str, object]:
        if not MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS:
            raise SchwabOvernightProbeError(
                f"Observation duration must be {MIN_DURATION_SECONDS} to "
                f"{MAX_DURATION_SECONDS} seconds."
            )
        started_at = _aware(self.utc_clock())
        session_start, session_end = overnight_window(started_at)
        if not session_start <= started_at < session_end:
            raise SchwabOvernightProbeError(
                "The live Schwab overnight probe requires the Sunday-night/overnight session."
            )

        access = self.access_guard.authorize(EXPECTED_ACCOUNT_ENDING)
        quote_request_at = _aware(self.utc_clock())
        quote_batch = self.quote_http.fetch_quotes_with_clock(
            access.access_token,
            SYMBOLS,
        )
        quote_received_at = _timestamp(
            str(quote_batch.clock_skew_proof["responseReceivedAt"])
        )
        quote_evidence = build_quote_evidence(
            quote_batch.quotes,
            receipt=quote_received_at,
        )

        bootstrap_request_at = _aware(self.utc_clock())
        bootstrap = parse_streamer_bootstrap(
            self.candle_http.fetch_bootstrap(access.access_token),
            expected_account_ending=EXPECTED_ACCOUNT_ENDING,
        )
        bootstrap_received_at = _aware(self.utc_clock())
        stream = self.stream_factory.connect(bootstrap.socket_url)
        messages: list[object] = []
        receipts: list[datetime] = []
        transport_events: list[dict[str, object]] = [
            {"kind": "CONNECTED", "timestamp": _aware(self.utc_clock()).isoformat()}
        ]
        stream_failure: str | None = None
        subscription_fingerprint = ""
        try:
            stream.send_json(build_streamer_login(access.access_token, bootstrap))
            _receive_ack(
                stream,
                monotonic_clock=self.monotonic_clock,
                utc_clock=self.utc_clock,
                service="ADMIN",
                command="LOGIN",
                request_id="0",
            )
            subscription = build_chart_equity_subscription(
                SYMBOLS,
                customer_id=bootstrap.customer_id,
                correlation_id=bootstrap.correlation_id,
                request_id="1",
            )
            subscription_fingerprint = hashlib.sha256(
                json.dumps(subscription, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                )
            ).hexdigest().upper()
            stream.send_json(subscription)
            _receive_ack(
                stream,
                monotonic_clock=self.monotonic_clock,
                utc_clock=self.utc_clock,
                service=SCHWAB_CHART_EQUITY_SERVICE,
                command="SUBS",
                request_id="1",
                messages=messages,
                receipts=receipts,
            )
            transport_events.append(
                {
                    "kind": "SUBSCRIPTION_ACKNOWLEDGED",
                    "timestamp": _aware(self.utc_clock()).isoformat(),
                }
            )
            observation_started = self.monotonic_clock()
            while self.monotonic_clock() - observation_started < duration_seconds:
                if len(messages) >= MAX_PROOF_MESSAGES:
                    raise SchwabOvernightProbeError(
                        "The overnight probe exceeded the bounded message limit."
                    )
                remaining = duration_seconds - (
                    self.monotonic_clock() - observation_started
                )
                try:
                    payload = stream.receive_json(max(0.1, min(5.0, remaining)))
                except (
                    SchwabCandleObserverNetworkError,
                    SchwabCandleObserverResponseError,
                ) as exc:
                    stream_failure = f"{type(exc).__name__}: {exc}"
                    transport_events.append(
                        {
                            "kind": "DISCONNECTED",
                            "timestamp": _aware(self.utc_clock()).isoformat(),
                        }
                    )
                    break
                if payload is None:
                    continue
                if "data" in payload:
                    inspect_chart_equity_observations(
                        [payload],
                        expected_symbols=SYMBOLS,
                        received_at_by_payload=[_aware(self.utc_clock())],
                    )
                    messages.append(payload)
                    receipts.append(_aware(self.utc_clock()))
        finally:
            stream.close()

        evaluated_at = _aware(self.utc_clock())
        transport_events.append(
            {"kind": "OBSERVATION_STOPPED", "timestamp": evaluated_at.isoformat()}
        )
        stream_observations = inspect_chart_equity_observations(
            messages,
            expected_symbols=SYMBOLS,
            received_at_by_payload=receipts,
        )
        stream_rows = [
            _stream_observation_evidence(observation)
            for observation in stream_observations
        ]

        history_evidence: dict[str, dict[str, object]] = {}
        history_rows_by_symbol: dict[str, list[dict[str, object]]] = {}
        for symbol in SYMBOLS:
            request_at = _aware(self.utc_clock())
            failure: str | None = None
            rows: list[dict[str, object]] = []
            try:
                payload = self.candle_http.fetch_price_history(
                    access.access_token,
                    symbol,
                    start_at=session_start,
                    end_at=evaluated_at + timedelta(minutes=1),
                    extended_hours=True,
                )
                candles = parse_price_history_response(
                    payload,
                    expected_symbol=symbol,
                )
                rows = [
                    _history_candle_evidence(candle.to_evidence())
                    for candle in candles
                    if session_start <= candle.timestamp < session_end
                ]
            except (SchwabCandleObserverError, ValueError) as exc:
                failure = f"{type(exc).__name__}: {exc}"
            received_at = _aware(self.utc_clock())
            history_rows_by_symbol[symbol] = rows
            history_evidence[symbol] = {
                "provider": "SCHWAB",
                "endpoint": "/marketdata/v1/pricehistory",
                "apiResult": "FAIL" if failure else "PASS",
                "failure": failure,
                "requestStartedAt": request_at.isoformat(),
                "responseReceivedAt": received_at.isoformat(),
                "explicitStartAt": session_start.isoformat(),
                "explicitEndAt": (evaluated_at + timedelta(minutes=1)).isoformat(),
                "extendedHoursRequested": True,
                **analyze_candle_rows(rows, receipt=received_at),
            }

        comparison = compare_stream_and_history(stream_rows, history_rows_by_symbol)
        stream_summary = analyze_stream_rows(stream_rows, receipt=evaluated_at)
        proof: dict[str, object] = {
            "schemaVersion": PROBE_SCHEMA,
            "mode": PROBE_MODE,
            "provider": "SCHWAB",
            "symbols": list(SYMBOLS),
            "observationWindow": {
                "startedAt": started_at.isoformat(),
                "completedAt": evaluated_at.isoformat(),
                "durationSeconds": duration_seconds,
                "sessionStart": session_start.isoformat(),
                "sessionEnd": session_end.isoformat(),
            },
            "accountInvariant": access.evidence(),
            "quotes": {
                "provider": "SCHWAB",
                "endpoint": "/marketdata/v1/quotes",
                "requestStartedAt": quote_request_at.isoformat(),
                "responseReceivedAt": quote_received_at.isoformat(),
                "apiResult": (
                    "PASS" if set(quote_evidence) == set(SYMBOLS) else "PARTIAL"
                ),
                "clockSkewProof": quote_batch.clock_skew_proof,
                "records": quote_evidence,
            },
            "stream": {
                "provider": "SCHWAB",
                "service": SCHWAB_CHART_EQUITY_SERVICE,
                "subscriptionAcknowledged": True,
                "subscriptionFingerprint": subscription_fingerprint,
                "bootstrapRequestStartedAt": bootstrap_request_at.isoformat(),
                "bootstrapResponseReceivedAt": bootstrap_received_at.isoformat(),
                "status": "FAIL" if stream_failure else "PASS",
                "failure": stream_failure,
                "transportEvents": transport_events,
                "observations": stream_rows,
                "summary": stream_summary,
            },
            "priceHistory": history_evidence,
            "streamHistoryComparison": comparison,
            "safety": {
                "readOnly": True,
                "accountInvariantReadRequired": True,
                "positionsRequested": False,
                "ordersRequested": False,
                "orderPreviewsRequested": False,
                "mutatingRequestAttempted": False,
                "productionPersistence": False,
                "serviceInvoked": False,
                "schedulerInvoked": False,
                "shadowInvoked": False,
                "brokerAdapterInvoked": False,
                "credentialMaterialIncluded": False,
                "orderTransmission": "UNAVAILABLE",
            },
            "authority": {
                "schwabRegularSession": "CANONICAL",
                "schwabOvernight": "UNVERIFIED_PENDING_ADJUDICATION",
                "executionAuthority": "NOT_GRANTED",
                "rankingAuthority": "NOT_GRANTED",
                "tradePlanAuthority": "NOT_GRANTED",
            },
        }
        proof["evidenceFingerprint"] = _fingerprint(proof)
        _require_sanitized(proof, forbidden_values=(access.access_token,))
        return proof


def overnight_window(observed_at: datetime) -> tuple[datetime, datetime]:
    eastern = _aware(observed_at).astimezone(EASTERN_TZ)
    local = eastern.time().replace(tzinfo=None)
    if local >= wall_time(20, 0):
        start = eastern.replace(hour=20, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=1)).replace(hour=4)
    else:
        end = eastern.replace(hour=4, minute=0, second=0, microsecond=0)
        start = (end - timedelta(days=1)).replace(hour=20)
    if start.weekday() not in (6, 0, 1, 2, 3):
        return start.astimezone(UTC), start.astimezone(UTC)
    return start.astimezone(UTC), end.astimezone(UTC)


def classify_overnight(timestamp: datetime) -> str:
    start, end = overnight_window(timestamp)
    return "OVERNIGHT" if start <= _aware(timestamp) < end else "OUTSIDE_OVERNIGHT"


def build_quote_evidence(
    quotes: Mapping[str, object],
    *,
    receipt: datetime,
) -> dict[str, dict[str, object]]:
    evidence: dict[str, dict[str, object]] = {}
    for symbol in SYMBOLS:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        quote_at = _timestamp(str(quote.provider_quote_timestamp))
        bid_at = _timestamp(str(quote.provider_bid_timestamp))
        ask_at = _timestamp(str(quote.provider_ask_timestamp))
        evidence[symbol] = {
            "provider": "SCHWAB",
            "symbol": symbol,
            "source": quote.source,
            "providerQuoteTimestamp": quote_at.isoformat(),
            "providerBidTimestamp": bid_at.isoformat(),
            "providerAskTimestamp": ask_at.isoformat(),
            "localReceiptTimestamp": receipt.isoformat(),
            "quoteAgeSeconds": _age(quote_at, receipt),
            "bidAgeSeconds": _age(bid_at, receipt),
            "askAgeSeconds": _age(ask_at, receipt),
            "bid": quote.bid,
            "ask": quote.ask,
            "latestTradePrice": quote.last,
            "latestTradeTimestamp": None,
            "latestTradeTimestampAvailable": False,
            "volume": quote.volume,
            "realtimeFlag": quote.realtime,
            "securityStatus": quote.security_status,
            "sessionClassification": classify_overnight(quote_at),
        }
    return evidence


def analyze_stream_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    receipt: datetime,
) -> dict[str, object]:
    by_symbol = {
        symbol: [row for row in rows if row.get("symbol") == symbol]
        for symbol in SYMBOLS
    }
    return {
        symbol: {
            **analyze_candle_rows(values, receipt=receipt),
            "observationCount": len(values),
            "revisionCount": sum(row.get("updateKind") == "REVISION" for row in values),
            "identicalReplayCount": sum(
                row.get("updateKind") == "IDENTICAL_REPLAY" for row in values
            ),
            "outOfOrderCount": sum(bool(row.get("outOfOrder")) for row in values),
            "currentMinuteUpdated": (
                "OBSERVED" if any(row.get("updateKind") == "REVISION" for row in values)
                else "NOT_OBSERVED"
            ),
        }
        for symbol, values in by_symbol.items()
    }


def analyze_candle_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    receipt: datetime,
) -> dict[str, object]:
    latest_by_timestamp: dict[datetime, Mapping[str, object]] = {}
    for row in rows:
        raw_timestamp = row.get("providerTimestamp") or row.get("timestamp")
        if raw_timestamp:
            latest_by_timestamp[_timestamp(str(raw_timestamp))] = row
    timestamps = sorted(latest_by_timestamp)
    missing: list[str] = []
    for previous, current in zip(timestamps, timestamps[1:]):
        cursor = previous + timedelta(minutes=1)
        while cursor < current:
            missing.append(cursor.isoformat())
            cursor += timedelta(minutes=1)
    final_rows = [latest_by_timestamp[timestamp] for timestamp in timestamps]
    highs = [_number(row.get("high")) for row in final_rows]
    lows = [_number(row.get("low")) for row in final_rows]
    volumes = [_number(row.get("volume")) for row in final_rows]
    latest = timestamps[-1] if timestamps else None
    return {
        "barCount": len(final_rows),
        "versionCount": len(rows),
        "firstMinute": timestamps[0].isoformat() if timestamps else None,
        "latestMinute": latest.isoformat() if latest else None,
        "latestAgeSeconds": _age(latest, receipt) if latest else None,
        "overnightHigh": max((value for value in highs if value is not None), default=None),
        "overnightLow": min((value for value in lows if value is not None), default=None),
        "cumulativeVolume": sum(value for value in volumes if value is not None),
        "missingMinuteCount": len(missing),
        "missingMinutes": missing,
        "duplicateMinuteCount": len(rows) - len(final_rows),
        "zeroVolumeBarCount": sum(value == 0 for value in volumes if value is not None),
        "ohlcvComplete": all(
            all(_number(row.get(field)) is not None for field in ("open", "high", "low", "close", "volume"))
            for row in final_rows
        ) if rows else False,
    }


def compare_stream_and_history(
    stream_rows: Sequence[Mapping[str, object]],
    history_rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    stream_latest = {
        (str(row["symbol"]), str(row["providerTimestamp"])): row
        for row in stream_rows
    }
    history_latest = {
        (symbol, str(row["providerTimestamp"])): row
        for symbol, rows in history_rows.items()
        for row in rows
    }
    common = sorted(set(stream_latest) & set(history_latest))
    mismatches: list[dict[str, object]] = []
    fields = ("open", "high", "low", "close", "volume")
    for key in common:
        changed = [
            field
            for field in fields
            if _number(stream_latest[key].get(field))
            != _number(history_latest[key].get(field))
        ]
        if changed:
            mismatches.append(
                {"symbol": key[0], "providerTimestamp": key[1], "fields": changed}
            )
    return {
        "comparableMinuteCount": len(common),
        "exactOhlcvMatchCount": len(common) - len(mismatches),
        "mismatchCount": len(mismatches),
        "mismatches": mismatches,
        "streamOnlyMinuteCount": len(set(stream_latest) - set(history_latest)),
        "historyOnlyMinuteCount": len(set(history_latest) - set(stream_latest)),
        "sourcesBlended": False,
    }


def write_proof(result: Mapping[str, object], *, output: Path) -> str:
    if output.exists():
        raise SchwabOvernightProbeError("The write-once Schwab overnight proof already exists.")
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def _receive_ack(
    stream: StreamConnection,
    *,
    monotonic_clock: Callable[[], float],
    utc_clock: Callable[[], datetime],
    service: str,
    command: str,
    request_id: str,
    messages: list[object] | None = None,
    receipts: list[datetime] | None = None,
) -> None:
    deadline = monotonic_clock() + ACK_TIMEOUT_SECONDS
    while monotonic_clock() < deadline:
        payload = stream.receive_json(max(0.1, min(2.0, deadline - monotonic_clock())))
        if payload is None:
            continue
        if "data" in payload:
            if messages is None or receipts is None:
                raise SchwabOvernightProbeError(
                    "Streamer sent candle data before subscription authorization completed."
                )
            messages.append(payload)
            receipts.append(_aware(utc_clock()))
        if "response" in payload:
            require_streamer_acknowledgement(
                payload,
                service=service,
                command=command,
                request_id=request_id,
            )
            return
    raise SchwabOvernightProbeError("Schwab Streamer acknowledgement timed out.")


def _stream_observation_evidence(observation: object) -> dict[str, object]:
    base = observation.to_evidence()
    candle = base.pop("candle")
    return {
        **base,
        "provider": "SCHWAB",
        "service": SCHWAB_CHART_EQUITY_SERVICE,
        "symbol": candle["symbol"],
        "providerTimestamp": candle["timestamp"],
        "localReceiptTimestamp": base["receivedAt"],
        "observedAgeSeconds": _age(
            _timestamp(str(candle["timestamp"])),
            _timestamp(str(base["receivedAt"])),
        ),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
        "sequence": candle["sequence"],
        "source": candle["source"],
        "sessionClassification": classify_overnight(
            _timestamp(str(candle["timestamp"]))
        ),
        "ohlcvComplete": candle["ohlcvComplete"],
    }


def _history_candle_evidence(candle: Mapping[str, object]) -> dict[str, object]:
    timestamp = _timestamp(str(candle["timestamp"]))
    return {
        "provider": "SCHWAB",
        "endpoint": "/marketdata/v1/pricehistory",
        "symbol": candle["symbol"],
        "providerTimestamp": timestamp.isoformat(),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
        "source": candle["source"],
        "sessionClassification": classify_overnight(timestamp),
        "ohlcvComplete": candle["ohlcvComplete"],
    }


def _require_sanitized(
    proof: Mapping[str, object],
    *,
    forbidden_values: Sequence[str],
) -> None:
    rendered = json.dumps(proof, sort_keys=True)
    if any(value and value in rendered for value in forbidden_values):
        raise SchwabOvernightProbeError("The Schwab overnight proof failed sanitation.")
    forbidden_keys = (
        '"access_token"',
        '"refresh_token"',
        '"accountHash"',
        '"customerId"',
        '"correlationId"',
    )
    if any(value in rendered for value in forbidden_keys):
        raise SchwabOvernightProbeError("The Schwab overnight proof exposed forbidden identity material.")


def _fingerprint(proof: Mapping[str, object]) -> str:
    payload = dict(proof)
    payload.pop("evidenceFingerprint", None)
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest().upper()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabOvernightProbeError("The Schwab overnight probe requires aware timestamps.")
    return value.astimezone(UTC)


def _age(provider_at: datetime, receipt: datetime) -> float:
    return round((_aware(receipt) - _aware(provider_at)).total_seconds(), 6)


def _number(value: object) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Run the read-only Schwab Sunday-night fidelity probe."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
    )
    args = parser.parse_args(argv)
    proof = SchwabOvernightFidelityProbe().observe(
        duration_seconds=args.duration_seconds,
    )
    proof_hash = write_proof(proof, output=args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": proof_hash,
                "symbols": list(SYMBOLS),
                "quoteResult": proof["quotes"]["apiResult"],
                "streamResult": proof["stream"]["status"],
                "ordersRequested": False,
                "positionsRequested": False,
                "productionPersistence": False,
                "credentialsIncluded": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
