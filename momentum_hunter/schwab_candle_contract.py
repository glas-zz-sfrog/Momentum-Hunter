"""Strict, nonpersisting contract boundary for Schwab minute candles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


SCHWAB_PRICE_HISTORY_URL = (
    "https://api.schwabapi.com/marketdata/v1/pricehistory"
)
SCHWAB_USER_PREFERENCE_URL = (
    "https://api.schwabapi.com/trader/v1/userPreference"
)
SCHWAB_CHART_EQUITY_SERVICE = "CHART_EQUITY"
SCHWAB_CHART_EQUITY_SOURCE = "schwab_streamer_chart_equity:v1"
SCHWAB_PRICE_HISTORY_SOURCE = "schwab_marketdata_v1_pricehistory:v1"
SCHWAB_CANDLE_CONTRACT_SCHEMA_VERSION = 1
SCHWAB_CANDLE_PROOF_SCHEMA_VERSION = 1
SCHWAB_CHART_EQUITY_FIELDS = "0,1,2,3,4,5,6,7,8"
MAX_PROOF_MESSAGES = 10_000
MAX_INPUT_BYTES = 8 * 1024 * 1024
EASTERN_TZ = ZoneInfo("America/New_York")
TRANSPORT_EVENT_KINDS = frozenset(
    {
        "CONNECTED",
        "SUBSCRIPTION_ACKNOWLEDGED",
        "DISCONNECTED",
        "RECONNECTED",
        "OBSERVATION_STOPPED",
    }
)


class SchwabCandleContractError(ValueError):
    pass


@dataclass(frozen=True)
class SchwabMinuteCandle:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    sequence: int | None = None

    def to_evidence(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "sessionDate": self.timestamp.astimezone(EASTERN_TZ).date().isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "sequence": self.sequence,
            "source": self.source,
            "ohlcvComplete": True,
        }


@dataclass(frozen=True)
class SchwabStreamCandleObservation:
    arrival_index: int
    payload_index: int
    received_at: datetime
    candle: SchwabMinuteCandle
    minute_identity: str
    update_kind: str
    changed_fields: tuple[str, ...]
    out_of_order: bool
    sequence_delta_from_previous_arrival: int | None

    def to_evidence(self) -> dict[str, object]:
        return {
            "arrivalIndex": self.arrival_index,
            "payloadIndex": self.payload_index,
            "receivedAt": self.received_at.isoformat(),
            "minuteIdentity": self.minute_identity,
            "updateKind": self.update_kind,
            "changedFields": list(self.changed_fields),
            "outOfOrder": self.out_of_order,
            "sequenceDeltaFromPreviousArrival": (
                self.sequence_delta_from_previous_arrival
            ),
            "candle": self.candle.to_evidence(),
        }


def official_candle_contract() -> dict[str, object]:
    """Return only behavior stated by Schwab's authenticated official docs."""

    return {
        "schemaVersion": SCHWAB_CANDLE_CONTRACT_SCHEMA_VERSION,
        "provider": "Charles Schwab Trader API - Individual",
        "authentication": {
            "flow": "OAuth2 authorizationCode",
            "scope": "readonly",
        },
        "stream": {
            "service": SCHWAB_CHART_EQUITY_SERVICE,
            "deliveryType": "All Sequence",
            "loginRequiredBeforeSubscription": True,
            "commands": ["SUBS", "ADD", "UNSUBS", "VIEW"],
            "symbolsPerKey": "comma-separated uppercase equities",
            "fields": {
                "key": "symbol",
                "1": "sequence",
                "2": "open",
                "3": "high",
                "4": "low",
                "5": "close",
                "6": "volume",
                "7": "chartTimeEpochMilliseconds",
                "8": "chartDay",
            },
            "regularHoursUpdates": True,
            "extendedHoursUpdates": True,
            "maximumConnectionsPerUser": 1,
            "numericSymbolLimit": None,
            "symbolLimitFailureCode": "REACHED_SYMBOL_LIMIT",
            "bootstrap": {
                "endpoint": SCHWAB_USER_PREFERENCE_URL,
                "method": "GET",
                "streamerFields": [
                    "streamerSocketUrl",
                    "schwabClientCustomerId",
                    "schwabClientCorrelId",
                    "schwabClientChannel",
                    "schwabClientFunctionId",
                ],
                "responseAlsoContainsAccountMetadata": True,
                "requiresSingleAccountInvariantValidation": True,
                "marketDataPermissionField": "offers[].mktDataPermission",
                "entitlementVerificationRequired": True,
            },
            "volumeSemantics": "total volume for the minute",
            "authoritativeConsolidatedVolume": None,
            "haltStatusIncludedInCandle": False,
        },
        "history": {
            "endpoint": SCHWAB_PRICE_HISTORY_URL,
            "method": "GET",
            "symbolsPerRequest": 1,
            "minuteFrequencies": [1, 5, 10, 15, 30],
            "dayPeriods": [1, 2, 3, 4, 5, 10],
            "periods": {
                "day": [1, 2, 3, 4, 5, 10],
                "month": [1, 2, 3, 6],
                "year": [1, 2, 3, 5, 10, 15, 20],
                "ytd": [1],
            },
            "frequencyTypes": {
                "day": ["minute"],
                "month": ["daily", "weekly"],
                "year": ["daily", "weekly", "monthly"],
                "ytd": ["daily", "weekly"],
            },
            "maximumDocumentedMinutePeriodDays": 10,
            "timestampFormat": "epoch milliseconds",
            "extendedHoursParameter": "needExtendedHoursData",
            "defaultEndDate": "previous business day market close",
            "explicitEndDateRequiredForNearCurrentProbe": True,
        },
        "notDocumented": [
            "stream candle completion/finality semantics",
            "normal delay after a minute closes",
            "corrections to previously emitted stream candles",
            "numeric CHART_EQUITY symbol limit",
            "REST polling or rate limits",
            "split and adjustment behavior",
            "price-history current-minute behavior",
            "consolidated/authoritative coverage of stream volume",
            "halt and stale-state signaling in CHART_EQUITY",
        ],
        "runtimeBoundary": {
            "researchOnly": True,
            "persisted": False,
            "accountDataIncluded": False,
            "brokerMethodsIncluded": False,
            "orderTransmission": "UNAVAILABLE",
        },
    }


def normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        )
    )
    if not normalized:
        raise SchwabCandleContractError(
            "At least one candle symbol is required."
        )
    if any(
        not symbol.replace(".", "").replace("-", "").isalnum()
        for symbol in normalized
    ):
        raise SchwabCandleContractError("A candle symbol was invalid.")
    return normalized


def build_chart_equity_subscription(
    symbols: Sequence[str],
    *,
    customer_id: str,
    correlation_id: str,
    request_id: str = "1",
) -> dict[str, object]:
    normalized = normalize_symbols(symbols)
    if not customer_id.strip() or not correlation_id.strip():
        raise SchwabCandleContractError(
            "Streamer customer and correlation identities are required."
        )
    if not str(request_id).strip():
        raise SchwabCandleContractError("Streamer request ID is required.")
    return {
        "requests": [
            {
                "service": SCHWAB_CHART_EQUITY_SERVICE,
                "command": "SUBS",
                "requestid": str(request_id),
                "SchwabClientCustomerId": customer_id,
                "SchwabClientCorrelId": correlation_id,
                "parameters": {
                    "keys": ",".join(normalized),
                    "fields": SCHWAB_CHART_EQUITY_FIELDS,
                },
            }
        ]
    }


def build_price_history_parameters(
    symbol: str,
    *,
    start_at: datetime,
    end_at: datetime,
    extended_hours: bool,
) -> dict[str, object]:
    normalized = normalize_symbols((symbol,))[0]
    start = _aware_datetime(start_at, "price-history start")
    end = _aware_datetime(end_at, "price-history end")
    if end <= start:
        raise SchwabCandleContractError(
            "Price-history end must be after its start."
        )
    return {
        "symbol": normalized,
        "periodType": "day",
        "frequencyType": "minute",
        "frequency": 1,
        "startDate": int(start.timestamp() * 1000),
        "endDate": int(end.timestamp() * 1000),
        "needExtendedHoursData": extended_hours,
        "needPreviousClose": True,
    }


def parse_chart_equity_messages(
    payloads: Sequence[object],
    *,
    expected_symbols: Sequence[str],
) -> tuple[SchwabMinuteCandle, ...]:
    expected = normalize_symbols(expected_symbols)
    if len(payloads) > MAX_PROOF_MESSAGES:
        raise SchwabCandleContractError(
            "Candle proof exceeded the message limit."
        )
    candles: list[SchwabMinuteCandle] = []
    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise SchwabCandleContractError(
                "Streamer payload had an invalid shape."
            )
        raw_frames = payload.get("data", [])
        if not isinstance(raw_frames, list):
            raise SchwabCandleContractError(
                "Streamer data collection had an invalid shape."
            )
        for frame in raw_frames:
            if not isinstance(frame, Mapping):
                raise SchwabCandleContractError(
                    "Streamer data frame had an invalid shape."
                )
            if str(frame.get("service", "")).strip() != SCHWAB_CHART_EQUITY_SERVICE:
                continue
            content = frame.get("content")
            if not isinstance(content, list):
                raise SchwabCandleContractError(
                    "CHART_EQUITY frame omitted candle content."
                )
            for row in content:
                candles.append(
                    _parse_chart_equity_row(row, expected_symbols=expected)
                )
    return tuple(candles)


def inspect_chart_equity_observations(
    payloads: Sequence[object],
    *,
    expected_symbols: Sequence[str],
    received_at_by_payload: Sequence[datetime],
) -> tuple[SchwabStreamCandleObservation, ...]:
    """Preserve arrival evidence without treating arrival order as candle order."""

    expected = normalize_symbols(expected_symbols)
    if len(payloads) != len(received_at_by_payload):
        raise SchwabCandleContractError(
            "Each Streamer payload requires one local receipt timestamp."
        )
    receipts = tuple(
        _aware_datetime(value, "payload receipt")
        for value in received_at_by_payload
    )
    if any(current < previous for previous, current in zip(receipts, receipts[1:])):
        raise SchwabCandleContractError(
            "Streamer payload receipt timestamps were not chronological."
        )

    observations: list[SchwabStreamCandleObservation] = []
    latest_version_by_minute: dict[
        tuple[str, str, datetime], SchwabMinuteCandle
    ] = {}
    greatest_timestamp_by_symbol: dict[str, datetime] = {}
    previous_arrival_by_symbol: dict[str, SchwabMinuteCandle] = {}
    for payload_index, (payload, received_at) in enumerate(
        zip(payloads, receipts)
    ):
        candles = parse_chart_equity_messages(
            [payload],
            expected_symbols=expected,
        )
        for candle in candles:
            key = (candle.source, candle.symbol, candle.timestamp)
            previous_version = latest_version_by_minute.get(key)
            if previous_version is None:
                update_kind = "FIRST_OBSERVATION"
                changed_fields: tuple[str, ...] = ()
            else:
                changed_fields = _changed_candle_fields(
                    previous_version,
                    candle,
                )
                update_kind = (
                    "REVISION" if changed_fields else "IDENTICAL_REPLAY"
                )
            greatest = greatest_timestamp_by_symbol.get(candle.symbol)
            out_of_order = greatest is not None and candle.timestamp < greatest
            previous_arrival = previous_arrival_by_symbol.get(candle.symbol)
            sequence_delta = (
                candle.sequence - previous_arrival.sequence
                if candle.sequence is not None
                and previous_arrival is not None
                and previous_arrival.sequence is not None
                else None
            )
            observation = SchwabStreamCandleObservation(
                arrival_index=len(observations),
                payload_index=payload_index,
                received_at=received_at,
                candle=candle,
                minute_identity=_minute_identity(candle),
                update_kind=update_kind,
                changed_fields=changed_fields,
                out_of_order=out_of_order,
                sequence_delta_from_previous_arrival=sequence_delta,
            )
            observations.append(observation)
            latest_version_by_minute[key] = candle
            previous_arrival_by_symbol[candle.symbol] = candle
            if greatest is None or candle.timestamp > greatest:
                greatest_timestamp_by_symbol[candle.symbol] = candle.timestamp
    return tuple(observations)


def parse_price_history_response(
    payload: object,
    *,
    expected_symbol: str,
) -> tuple[SchwabMinuteCandle, ...]:
    expected = normalize_symbols((expected_symbol,))[0]
    if not isinstance(payload, Mapping):
        raise SchwabCandleContractError(
            "Price-history response had an invalid shape."
        )
    symbol = str(payload.get("symbol", "")).strip().upper()
    if symbol != expected:
        raise SchwabCandleContractError(
            "Price-history symbol identity did not match the request."
        )
    empty = payload.get("empty")
    rows = payload.get("candles")
    if not isinstance(empty, bool) or not isinstance(rows, list):
        raise SchwabCandleContractError(
            "Price-history response omitted its empty/candles contract."
        )
    if empty and rows:
        raise SchwabCandleContractError(
            "Price-history response contradicted its empty flag."
        )
    if not empty and not rows:
        raise SchwabCandleContractError(
            "Price-history response declared data but returned no candles."
        )
    candles = tuple(
        _parse_price_history_row(row, symbol=expected) for row in rows
    )
    _require_strict_event_order(candles)
    return candles


def build_nonpersisting_stream_proof(
    payloads: Sequence[object],
    *,
    expected_symbols: Sequence[str],
    request_started_at: datetime,
    response_received_at: datetime,
    evaluated_at: datetime | None = None,
    received_at_by_payload: Sequence[datetime] | None = None,
    transport_events: Sequence[Mapping[str, object]] = (),
    price_history_payloads: Mapping[str, object] | None = None,
) -> dict[str, object]:
    requested = _aware_datetime(request_started_at, "request start")
    received = _aware_datetime(response_received_at, "response receipt")
    evaluated = _aware_datetime(
        evaluated_at or response_received_at,
        "proof evaluation",
    )
    if received < requested or evaluated < received:
        raise SchwabCandleContractError(
            "Candle proof timestamps were not chronological."
        )
    expected = normalize_symbols(expected_symbols)
    receipt_times = (
        tuple(received_at_by_payload)
        if received_at_by_payload is not None
        else tuple(received for _ in payloads)
    )
    observations = inspect_chart_equity_observations(
        payloads,
        expected_symbols=expected,
        received_at_by_payload=receipt_times,
    )
    payload_fingerprints = [
        {
            "payloadIndex": payload_index,
            "receivedAt": receipt_times[payload_index].isoformat(),
            "sha256": hashlib.sha256(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest().upper(),
        }
        for payload_index, payload in enumerate(payloads)
    ]
    if any(observation.received_at > evaluated for observation in observations):
        raise SchwabCandleContractError(
            "A Streamer payload receipt was later than proof evaluation."
        )
    normalized_transport_events = _normalize_transport_events(
        transport_events,
        evaluated_at=evaluated,
    )
    latest_by_symbol: dict[str, SchwabStreamCandleObservation] = {}
    for observation in observations:
        previous = latest_by_symbol.get(observation.candle.symbol)
        if previous is None or (
            observation.candle.timestamp,
            observation.arrival_index,
        ) >= (
            previous.candle.timestamp,
            previous.arrival_index,
        ):
            latest_by_symbol[observation.candle.symbol] = observation

    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for symbol in expected:
        observation = latest_by_symbol.get(symbol)
        if observation is None:
            missing.append(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "status": "MISSING",
                    "ohlcvComplete": False,
                }
            )
            continue
        candle = observation.candle
        age_seconds = (evaluated - candle.timestamp).total_seconds()
        rows.append(
            {
                **candle.to_evidence(),
                "status": "PASS" if age_seconds >= 0 else "FAIL",
                "ageAtEvaluationSeconds": round(age_seconds, 6),
                "session": session_for_timestamp(candle.timestamp),
            }
        )

    newest = max(
        (
            observation.candle.timestamp
            for observation in latest_by_symbol.values()
        ),
        default=None,
    )
    shape_pass = not missing and all(row["status"] == "PASS" for row in rows)
    proof_status = "PARTIAL" if shape_pass else "FAIL"
    market_minute = evaluated.astimezone(EASTERN_TZ).replace(
        second=0,
        microsecond=0,
    )
    minute_summaries = _summarize_observed_minutes(
        observations,
        evaluated_at=evaluated,
    )
    observed_gaps = _observed_timestamp_gaps(observations)
    reconciliation = (
        compare_stream_observations_to_price_history(
            observations,
            price_history_payloads=price_history_payloads,
        )
        if price_history_payloads is not None
        else None
    )
    findings = (
        ["COMPLETION_SEMANTICS_REQUIRE_LIVE_MARKET_PROOF"]
        if shape_pass
        else ["EXPECTED_CANDLE_MISSING_OR_INVALID"]
    )
    if any(observation.out_of_order for observation in observations):
        findings.append("OUT_OF_ORDER_STREAM_UPDATE_OBSERVED")
    if any(
        observation.update_kind == "IDENTICAL_REPLAY"
        for observation in observations
    ):
        findings.append("IDENTICAL_STREAM_REPLAY_OBSERVED")
    if any(
        observation.update_kind == "REVISION"
        for observation in observations
    ):
        findings.append("INTRA_MINUTE_STREAM_REVISION_OBSERVED")
    if observed_gaps:
        findings.append("OBSERVED_TIMESTAMP_GAP_REQUIRES_RECONCILIATION")
    if reconciliation and not reconciliation["allComparableMinutesMatch"]:
        findings.append("STREAM_HISTORY_DIFFERENCE_OBSERVED")
    return {
        "schemaVersion": SCHWAB_CANDLE_PROOF_SCHEMA_VERSION,
        "proofType": "SCHWAB_CHART_EQUITY_NONPERSISTING_SHAPE_LATENCY",
        "proofStatus": proof_status,
        "shapeStatus": "PASS" if shape_pass else "FAIL",
        "completionStatus": "UNVERIFIED",
        "latencyStatus": "OBSERVED_NOT_YET_ACCEPTANCE_GRADED",
        "requestStartedAt": requested.isoformat(),
        "responseReceivedAt": received.isoformat(),
        "evaluatedAt": evaluated.isoformat(),
        "providerResponseSeconds": round(
            (received - requested).total_seconds(),
            6,
        ),
        "currentMarketMinute": market_minute.isoformat(),
        "newestCandleTimestamp": newest.isoformat() if newest else None,
        "newestObservedCandleAgeSeconds": (
            round((evaluated - newest).total_seconds(), 6)
            if newest
            else None
        ),
        "newestCompletedBarTimestamp": None,
        "newestCompletedBarAgeSeconds": None,
        "completionSemantics": "UNVERIFIED_BY_OFFICIAL_CONTRACT",
        "extendedHoursObserved": any(
            row.get("session") == "extended" for row in rows
        ),
        "sourceIdentity": SCHWAB_CHART_EQUITY_SOURCE,
        "requestedSymbols": list(expected),
        "missingSymbols": missing,
        "candles": rows,
        "transportEvents": normalized_transport_events,
        "updateObservations": [
            observation.to_evidence() for observation in observations
        ],
        "payloadFingerprints": payload_fingerprints,
        "minuteSummaries": minute_summaries,
        "observedTimestampGaps": observed_gaps,
        "streamHistoryReconciliation": reconciliation,
        "findings": findings,
        "nonPersisting": True,
        "networkCalledByProofBuilder": False,
        "accountDataIncluded": False,
        "brokerMethodsIncluded": False,
        "orderTransmission": "UNAVAILABLE",
    }


def compare_stream_observations_to_price_history(
    observations: Sequence[SchwabStreamCandleObservation],
    *,
    price_history_payloads: Mapping[str, object],
) -> dict[str, object]:
    """Compare the last observed stream version with immutable REST evidence."""

    normalized_payloads: dict[str, object] = {}
    for raw_symbol, payload in price_history_payloads.items():
        symbol = normalize_symbols((raw_symbol,))[0]
        if symbol in normalized_payloads:
            raise SchwabCandleContractError(
                "Price-history reconciliation repeated a symbol."
            )
        normalized_payloads[symbol] = payload

    latest_stream: dict[tuple[str, datetime], SchwabMinuteCandle] = {}
    for observation in observations:
        latest_stream[
            (observation.candle.symbol, observation.candle.timestamp)
        ] = observation.candle

    history: dict[tuple[str, datetime], SchwabMinuteCandle] = {}
    for symbol, payload in normalized_payloads.items():
        for candle in parse_price_history_response(
            payload,
            expected_symbol=symbol,
        ):
            history[(symbol, candle.timestamp)] = candle

    rows: list[dict[str, object]] = []
    comparable_matches = 0
    comparable_differences = 0
    stream_only = 0
    history_only = 0
    for symbol, timestamp in sorted(
        set(latest_stream) | set(history),
        key=lambda item: (item[0], item[1]),
    ):
        stream_candle = latest_stream.get((symbol, timestamp))
        history_candle = history.get((symbol, timestamp))
        if stream_candle is None:
            status = "HISTORY_ONLY"
            changed_fields: tuple[str, ...] = ()
            history_only += 1
        elif history_candle is None:
            status = "STREAM_ONLY"
            changed_fields = ()
            stream_only += 1
        else:
            changed_fields = _changed_candle_fields(
                stream_candle,
                history_candle,
            )
            if changed_fields:
                status = "CORRECTED_OR_DIFFERENT"
                comparable_differences += 1
            else:
                status = "MATCH"
                comparable_matches += 1
        rows.append(
            {
                "minuteIdentity": (
                    _minute_identity(stream_candle)
                    if stream_candle is not None
                    else _minute_identity(history_candle)
                ),
                "symbol": symbol,
                "timestamp": timestamp.isoformat(),
                "status": status,
                "changedFields": list(changed_fields),
                "stream": (
                    stream_candle.to_evidence()
                    if stream_candle is not None
                    else None
                ),
                "priceHistory": (
                    history_candle.to_evidence()
                    if history_candle is not None
                    else None
                ),
            }
        )

    comparable = comparable_matches + comparable_differences
    return {
        "schemaVersion": SCHWAB_CANDLE_PROOF_SCHEMA_VERSION,
        "comparison": "LATEST_STREAM_VERSION_VS_PRICE_HISTORY",
        "allComparableMinutesMatch": (
            comparable > 0 and comparable_differences == 0
        ),
        "comparableMinuteCount": comparable,
        "matchingMinuteCount": comparable_matches,
        "differentMinuteCount": comparable_differences,
        "streamOnlyMinuteCount": stream_only,
        "historyOnlyMinuteCount": history_only,
        "rows": rows,
        "streamSource": SCHWAB_CHART_EQUITY_SOURCE,
        "historySource": SCHWAB_PRICE_HISTORY_SOURCE,
        "canonicalityGranted": False,
        "nonPersisting": True,
    }


def session_for_timestamp(observed_at: datetime) -> str:
    eastern = observed_at.astimezone(EASTERN_TZ)
    if eastern.weekday() >= 5:
        return "closed"
    local = eastern.time().replace(tzinfo=None)
    if time(9, 30) <= local < time(16, 0):
        return "regular"
    if time(4, 0) <= local < time(9, 30) or time(16, 0) <= local < time(20, 0):
        return "extended"
    return "closed"


def _minute_identity(candle: SchwabMinuteCandle | None) -> str:
    if candle is None:
        raise SchwabCandleContractError(
            "Minute identity requires candle evidence."
        )
    return "|".join(
        (
            candle.source,
            candle.symbol,
            candle.timestamp.astimezone(EASTERN_TZ).date().isoformat(),
            candle.timestamp.isoformat(),
        )
    )


def _changed_candle_fields(
    previous: SchwabMinuteCandle,
    current: SchwabMinuteCandle,
) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("open", "high", "low", "close", "volume")
        if getattr(previous, name) != getattr(current, name)
    )


def _summarize_observed_minutes(
    observations: Sequence[SchwabStreamCandleObservation],
    *,
    evaluated_at: datetime,
) -> list[dict[str, object]]:
    grouped: dict[str, list[SchwabStreamCandleObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.minute_identity, []).append(observation)
    summaries: list[dict[str, object]] = []
    for minute_identity in sorted(grouped):
        versions = grouped[minute_identity]
        first = versions[0]
        last_changed = first.received_at
        for observation in versions[1:]:
            if observation.update_kind == "REVISION":
                last_changed = observation.received_at
        latest = versions[-1]
        summaries.append(
            {
                "minuteIdentity": minute_identity,
                "symbol": latest.candle.symbol,
                "candleTimestamp": latest.candle.timestamp.isoformat(),
                "firstObservedAt": first.received_at.isoformat(),
                "lastObservedAt": latest.received_at.isoformat(),
                "lastChangedAt": last_changed.isoformat(),
                "observedStableForSeconds": round(
                    (evaluated_at - last_changed).total_seconds(),
                    6,
                ),
                "updateCount": len(versions),
                "revisionCount": sum(
                    observation.update_kind == "REVISION"
                    for observation in versions
                ),
                "identicalReplayCount": sum(
                    observation.update_kind == "IDENTICAL_REPLAY"
                    for observation in versions
                ),
                "outOfOrderArrivalCount": sum(
                    observation.out_of_order for observation in versions
                ),
                "latestObservedCandle": latest.candle.to_evidence(),
                "completionState": "UNVERIFIED",
            }
        )
    return summaries


def _observed_timestamp_gaps(
    observations: Sequence[SchwabStreamCandleObservation],
) -> list[dict[str, object]]:
    timestamps_by_symbol: dict[str, set[datetime]] = {}
    for observation in observations:
        timestamps_by_symbol.setdefault(
            observation.candle.symbol,
            set(),
        ).add(observation.candle.timestamp)
    gaps: list[dict[str, object]] = []
    for symbol, timestamps in sorted(timestamps_by_symbol.items()):
        ordered = sorted(timestamps)
        for previous, current in zip(ordered, ordered[1:]):
            previous_eastern = previous.astimezone(EASTERN_TZ)
            current_eastern = current.astimezone(EASTERN_TZ)
            if previous_eastern.date() != current_eastern.date():
                continue
            elapsed_seconds = (current - previous).total_seconds()
            if elapsed_seconds <= 60:
                continue
            gaps.append(
                {
                    "symbol": symbol,
                    "afterTimestamp": previous.isoformat(),
                    "beforeTimestamp": current.isoformat(),
                    "observedMissingMinuteCount": max(
                        0,
                        int(elapsed_seconds // 60) - 1,
                    ),
                    "classification": "OBSERVED_TIMESTAMP_GAP",
                    "dataLossProven": False,
                }
            )
    return gaps


def _normalize_transport_events(
    events: Sequence[Mapping[str, object]],
    *,
    evaluated_at: datetime,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    previous: datetime | None = None
    for event in events:
        kind = str(event.get("kind", "")).strip().upper()
        if kind not in TRANSPORT_EVENT_KINDS:
            raise SchwabCandleContractError(
                "Candle transport event kind was invalid."
            )
        raw_timestamp = event.get("timestamp")
        if isinstance(raw_timestamp, datetime):
            timestamp = _aware_datetime(raw_timestamp, "transport event")
        elif isinstance(raw_timestamp, str):
            timestamp = _parse_cli_datetime(raw_timestamp)
        else:
            raise SchwabCandleContractError(
                "Candle transport event timestamp was invalid."
            )
        if timestamp > evaluated_at or (
            previous is not None and timestamp < previous
        ):
            raise SchwabCandleContractError(
                "Candle transport events were not chronological."
            )
        normalized.append({"kind": kind, "timestamp": timestamp.isoformat()})
        previous = timestamp
    return normalized


def _parse_chart_equity_row(
    row: object,
    *,
    expected_symbols: Sequence[str],
) -> SchwabMinuteCandle:
    if not isinstance(row, Mapping):
        raise SchwabCandleContractError(
            "CHART_EQUITY candle had an invalid shape."
        )
    indexed_symbol = row.get("0", row.get(0))
    keyed_symbol = row.get("key")
    if indexed_symbol is None and keyed_symbol is None:
        raise SchwabCandleContractError(
            "CHART_EQUITY candle omitted its symbol identity."
        )
    if (
        indexed_symbol is not None
        and keyed_symbol is not None
        and str(indexed_symbol).strip().upper()
        != str(keyed_symbol).strip().upper()
    ):
        raise SchwabCandleContractError(
            "CHART_EQUITY candle returned conflicting symbol identities."
        )
    symbol = str(
        keyed_symbol if keyed_symbol is not None else indexed_symbol
    ).strip().upper()
    if symbol not in expected_symbols:
        raise SchwabCandleContractError(
            "CHART_EQUITY returned an unexpected symbol."
        )
    candle = SchwabMinuteCandle(
        symbol=symbol,
        open=_positive_number(_field(row, 2), "open"),
        high=_positive_number(_field(row, 3), "high"),
        low=_positive_number(_field(row, 4), "low"),
        close=_positive_number(_field(row, 5), "close"),
        volume=_nonnegative_number(_field(row, 6), "volume"),
        sequence=_nonnegative_integer(_field(row, 1), "sequence"),
        timestamp=_epoch_milliseconds(_field(row, 7), "chart time"),
        source=SCHWAB_CHART_EQUITY_SOURCE,
    )
    _validate_ohlc(candle)
    return candle


def _parse_price_history_row(
    row: object,
    *,
    symbol: str,
) -> SchwabMinuteCandle:
    if not isinstance(row, Mapping):
        raise SchwabCandleContractError(
            "Price-history candle had an invalid shape."
        )
    candle = SchwabMinuteCandle(
        symbol=symbol,
        open=_positive_number(row.get("open"), "open"),
        high=_positive_number(row.get("high"), "high"),
        low=_positive_number(row.get("low"), "low"),
        close=_positive_number(row.get("close"), "close"),
        volume=_nonnegative_number(row.get("volume"), "volume"),
        sequence=None,
        timestamp=_epoch_milliseconds(row.get("datetime"), "datetime"),
        source=SCHWAB_PRICE_HISTORY_SOURCE,
    )
    _validate_ohlc(candle)
    return candle


def _field(row: Mapping[object, object], index: int) -> object:
    if str(index) in row:
        return row[str(index)]
    if index in row:
        return row[index]
    raise SchwabCandleContractError(
        f"CHART_EQUITY candle omitted field {index}."
    )


def _positive_number(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0:
        raise SchwabCandleContractError(
            f"Candle {name} must be positive."
        )
    return number


def _nonnegative_number(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0:
        raise SchwabCandleContractError(
            f"Candle {name} must be nonnegative."
        )
    return number


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabCandleContractError(
            f"Candle {name} must be numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise SchwabCandleContractError(
            f"Candle {name} must be finite."
        )
    return number


def _nonnegative_integer(value: object, name: str) -> int:
    number = _finite_number(value, name)
    if number < 0 or not number.is_integer():
        raise SchwabCandleContractError(
            f"Candle {name} must be a nonnegative integer; observed {number!r}."
        )
    return int(number)


def _epoch_milliseconds(value: object, name: str) -> datetime:
    milliseconds = _finite_number(value, name)
    if milliseconds <= 0:
        raise SchwabCandleContractError(
            f"Candle {name} must be a positive epoch timestamp."
        )
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise SchwabCandleContractError(
            f"Candle {name} was outside the supported timestamp range."
        ) from None


def _validate_ohlc(candle: SchwabMinuteCandle) -> None:
    if candle.high < max(candle.open, candle.low, candle.close):
        raise SchwabCandleContractError(
            "Candle high was below another OHLC value; "
            f"observed open={candle.open!r}, high={candle.high!r}, "
            f"low={candle.low!r}, close={candle.close!r}."
        )
    if candle.low > min(candle.open, candle.high, candle.close):
        raise SchwabCandleContractError(
            "Candle low was above another OHLC value; "
            f"observed open={candle.open!r}, high={candle.high!r}, "
            f"low={candle.low!r}, close={candle.close!r}."
        )


def _require_strict_event_order(
    candles: Sequence[SchwabMinuteCandle],
) -> None:
    previous: dict[str, datetime] = {}
    identities: set[tuple[str, datetime, int | None]] = set()
    for candle in candles:
        identity = (candle.symbol, candle.timestamp, candle.sequence)
        if identity in identities:
            raise SchwabCandleContractError(
                "Candle evidence contained a duplicate event identity."
            )
        identities.add(identity)
        last = previous.get(candle.symbol)
        if last is not None and candle.timestamp <= last:
            raise SchwabCandleContractError(
                "Candle evidence was not strictly chronological."
            )
        previous[candle.symbol] = candle.timestamp


def _aware_datetime(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabCandleContractError(
            f"Candle {name} must include a UTC offset."
        )
    return value


def _parse_cli_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware_datetime(parsed, "CLI timestamp")


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise SchwabCandleContractError("Candle input file does not exist.")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise SchwabCandleContractError("Candle input file exceeded the size limit.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SchwabCandleContractError(
            "Candle input file was not valid UTF-8 JSON."
        ) from None


def _decode_stream_proof_input(
    raw: object,
    *,
    fallback_received_at: datetime,
) -> tuple[
    list[object],
    list[datetime],
    list[Mapping[str, object]],
    Mapping[str, object] | None,
]:
    if isinstance(raw, Mapping) and "messages" in raw:
        messages = raw.get("messages")
        if not isinstance(messages, list):
            raise SchwabCandleContractError(
                "Stream proof messages had an invalid shape."
            )
        payloads: list[object] = []
        receipts: list[datetime] = []
        for message in messages:
            if not isinstance(message, Mapping) or "payload" not in message:
                raise SchwabCandleContractError(
                    "Stream proof message omitted its payload."
                )
            received_at = message.get("receivedAt")
            if not isinstance(received_at, str):
                raise SchwabCandleContractError(
                    "Stream proof message omitted its local receipt time."
                )
            payloads.append(message["payload"])
            receipts.append(_parse_cli_datetime(received_at))
        raw_events = raw.get("transportEvents", [])
        if not isinstance(raw_events, list) or any(
            not isinstance(event, Mapping) for event in raw_events
        ):
            raise SchwabCandleContractError(
                "Stream proof transport events had an invalid shape."
            )
        raw_history = raw.get("priceHistory")
        if raw_history is not None and not isinstance(raw_history, Mapping):
            raise SchwabCandleContractError(
                "Stream proof price history had an invalid shape."
            )
        return payloads, receipts, raw_events, raw_history

    payloads = raw if isinstance(raw, list) else [raw]
    return (
        list(payloads),
        [fallback_received_at for _ in payloads],
        [],
        None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Schwab candle contracts without persistence or trading."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("contract")

    stream = subparsers.add_parser("inspect-stream")
    stream.add_argument("--input", type=Path, required=True)
    stream.add_argument("--symbols", nargs="+", required=True)
    stream.add_argument("--request-started-at", required=True)
    stream.add_argument("--response-received-at", required=True)
    stream.add_argument("--evaluated-at")

    history = subparsers.add_parser("inspect-pricehistory")
    history.add_argument("--input", type=Path, required=True)
    history.add_argument("--symbol", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            result = official_candle_contract()
        elif args.command == "inspect-stream":
            raw = _load_json(args.input)
            response_received_at = _parse_cli_datetime(
                args.response_received_at
            )
            (
                payloads,
                receipt_times,
                transport_events,
                price_history_payloads,
            ) = _decode_stream_proof_input(
                raw,
                fallback_received_at=response_received_at,
            )
            result = build_nonpersisting_stream_proof(
                payloads,
                expected_symbols=args.symbols,
                request_started_at=_parse_cli_datetime(
                    args.request_started_at
                ),
                response_received_at=response_received_at,
                evaluated_at=(
                    _parse_cli_datetime(args.evaluated_at)
                    if args.evaluated_at
                    else None
                ),
                received_at_by_payload=receipt_times,
                transport_events=transport_events,
                price_history_payloads=price_history_payloads,
            )
        else:
            candles = parse_price_history_response(
                _load_json(args.input),
                expected_symbol=args.symbol,
            )
            result = {
                "schemaVersion": SCHWAB_CANDLE_PROOF_SCHEMA_VERSION,
                "proofType": "SCHWAB_PRICE_HISTORY_SHAPE",
                "proofStatus": "PASS",
                "sourceIdentity": SCHWAB_PRICE_HISTORY_SOURCE,
                "symbol": normalize_symbols((args.symbol,))[0],
                "candleCount": len(candles),
                "candles": [candle.to_evidence() for candle in candles],
                "completionSemantics": "UNVERIFIED_BY_OFFICIAL_CONTRACT",
                "nonPersisting": True,
                "networkCalled": False,
                "accountDataIncluded": False,
                "orderTransmission": "UNAVAILABLE",
            }
    except (SchwabCandleContractError, ValueError) as exc:
        result = {
            "schemaVersion": SCHWAB_CANDLE_PROOF_SCHEMA_VERSION,
            "proofStatus": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
            "nonPersisting": True,
            "networkCalled": False,
            "accountDataIncluded": False,
            "orderTransmission": "UNAVAILABLE",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result.get("proofStatus") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
