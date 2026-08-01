"""Strict, nonpersisting contract boundary for Schwab minute candles."""

from __future__ import annotations

import argparse
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
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "sequence": self.sequence,
            "source": self.source,
            "ohlcvComplete": True,
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
                "0": "symbol",
                "1": "open",
                "2": "high",
                "3": "low",
                "4": "close",
                "5": "volume",
                "6": "sequence",
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
    _require_strict_event_order(candles)
    return tuple(candles)


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
    candles = parse_chart_equity_messages(
        payloads,
        expected_symbols=expected,
    )
    latest_by_symbol: dict[str, SchwabMinuteCandle] = {}
    for candle in candles:
        latest_by_symbol[candle.symbol] = candle

    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for symbol in expected:
        candle = latest_by_symbol.get(symbol)
        if candle is None:
            missing.append(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "status": "MISSING",
                    "ohlcvComplete": False,
                }
            )
            continue
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
        (candle.timestamp for candle in latest_by_symbol.values()),
        default=None,
    )
    shape_pass = not missing and all(row["status"] == "PASS" for row in rows)
    proof_status = "PARTIAL" if shape_pass else "FAIL"
    market_minute = evaluated.astimezone(EASTERN_TZ).replace(
        second=0,
        microsecond=0,
    )
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
        "findings": (
            ["COMPLETION_SEMANTICS_REQUIRE_LIVE_MARKET_PROOF"]
            if shape_pass
            else ["EXPECTED_CANDLE_MISSING_OR_INVALID"]
        ),
        "nonPersisting": True,
        "networkCalledByProofBuilder": False,
        "accountDataIncluded": False,
        "brokerMethodsIncluded": False,
        "orderTransmission": "UNAVAILABLE",
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


def _parse_chart_equity_row(
    row: object,
    *,
    expected_symbols: Sequence[str],
) -> SchwabMinuteCandle:
    if not isinstance(row, Mapping):
        raise SchwabCandleContractError(
            "CHART_EQUITY candle had an invalid shape."
        )
    symbol = str(_field(row, 0)).strip().upper()
    if symbol not in expected_symbols:
        raise SchwabCandleContractError(
            "CHART_EQUITY returned an unexpected symbol."
        )
    candle = SchwabMinuteCandle(
        symbol=symbol,
        open=_positive_number(_field(row, 1), "open"),
        high=_positive_number(_field(row, 2), "high"),
        low=_positive_number(_field(row, 3), "low"),
        close=_positive_number(_field(row, 4), "close"),
        volume=_nonnegative_number(_field(row, 5), "volume"),
        sequence=_positive_integer(_field(row, 6), "sequence"),
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


def _positive_integer(value: object, name: str) -> int:
    number = _finite_number(value, name)
    if number <= 0 or not number.is_integer():
        raise SchwabCandleContractError(
            f"Candle {name} must be a positive integer."
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
            "Candle high was below another OHLC value."
        )
    if candle.low > min(candle.open, candle.high, candle.close):
        raise SchwabCandleContractError(
            "Candle low was above another OHLC value."
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
            payloads = raw if isinstance(raw, list) else [raw]
            result = build_nonpersisting_stream_proof(
                payloads,
                expected_symbols=args.symbols,
                request_started_at=_parse_cli_datetime(
                    args.request_started_at
                ),
                response_received_at=_parse_cli_datetime(
                    args.response_received_at
                ),
                evaluated_at=(
                    _parse_cli_datetime(args.evaluated_at)
                    if args.evaluated_at
                    else None
                ),
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
