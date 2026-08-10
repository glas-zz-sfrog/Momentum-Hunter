from __future__ import annotations

"""Read-only, sanitized Alpaca Sunday-night market-data capability probe."""

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from momentum_hunter.alpaca_paper_onboarding import (
    AlpacaPaperCredentialRepository,
    AlpacaPaperCredentials,
    AlpacaPaperLane,
)


ALPACA_MARKET_DATA_BASE_URL = "https://data.alpaca.markets"
ALPACA_MARKET_DATA_HOST = "data.alpaca.markets"
PROBE_SCHEMA = "ALPACA_OVERNIGHT_CAPABILITY_PROBE_V1"
PROBE_MODE = "READ_ONLY_CONTEXT_RESEARCH"
SYMBOLS = ("SPY", "QQQ", "NVDA")
LATEST_FEEDS = ("overnight", "boats")
LATEST_PATHS = {
    "latestBar": "/v2/stocks/bars/latest",
    "latestQuote": "/v2/stocks/quotes/latest",
    "latestTrade": "/v2/stocks/trades/latest",
    "snapshot": "/v2/stocks/snapshots",
}
HISTORICAL_BAR_PATH = re.compile(r"/v2/stocks/[A-Z][A-Z0-9.\-]{0,14}/bars")
HTTP_TIMEOUT = (5.0, 15.0)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


class AlpacaOvernightProbeError(RuntimeError):
    pass


class AlpacaOvernightEndpointError(AlpacaOvernightProbeError):
    pass


class AlpacaOvernightResponseError(AlpacaOvernightProbeError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


class AlpacaOvernightTransport:
    """Exact-host GET-only transport with no account, position, or order routes."""

    def __init__(
        self,
        *,
        base_url: str = ALPACA_MARKET_DATA_BASE_URL,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require_market_data_endpoint(base_url)
        self.base_url = base_url
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(UTC))

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, object],
        credentials: AlpacaPaperCredentials,
        feed: str,
        data_type: str,
    ) -> tuple[dict[str, object], object | None]:
        _require_allowed_path(path)
        request_start = _utc(self.clock())
        status_code: int | None = None
        payload: object | None = None
        error = ""
        request_id_present = False
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                headers={
                    "Accept": "application/json",
                    "APCA-API-KEY-ID": credentials.key_id,
                    "APCA-API-SECRET-KEY": credentials.secret_key,
                    "Cache-Control": "no-store",
                },
                params=dict(params),
                timeout=self.timeout,
                allow_redirects=False,
            )
            receipt = _utc(self.clock())
            status_code = int(response.status_code)
            request_id_present = bool(response.headers.get("X-Request-ID"))
            if response.is_redirect:
                raise AlpacaOvernightEndpointError(
                    "The market-data probe refused an HTTP redirect."
                )
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise AlpacaOvernightResponseError(
                    "The market-data response exceeded the bounded size limit."
                )
            try:
                payload = response.json()
            except ValueError:
                error = "INVALID_JSON"
            if status_code != 200:
                error = _provider_error(payload, status_code, credentials)
                payload = None
        except requests.RequestException as exc:
            receipt = _utc(self.clock())
            error = _sanitize_text(type(exc).__name__, credentials)
        except AlpacaOvernightProbeError:
            raise

        observation = {
            "provider": "Alpaca Market Data",
            "endpointHost": ALPACA_MARKET_DATA_HOST,
            "requestMethod": "GET",
            "requestPath": path,
            "feed": feed,
            "dataType": data_type,
            "symbols": list(_symbols_from_params(params, path)),
            "requestStart": request_start.isoformat(),
            "responseReceipt": receipt.isoformat(),
            "apiStatus": status_code,
            "apiResult": "SUCCESS" if status_code == 200 and payload is not None else "FAIL",
            "requestIdPresent": request_id_present,
            "error": error,
            "credentialValuesIncluded": False,
        }
        return observation, payload


def run_probe(
    *,
    credentials: AlpacaPaperCredentialRepository | None = None,
    transport: AlpacaOvernightTransport | None = None,
    symbols: Sequence[str] = SYMBOLS,
    now: datetime | None = None,
    repeat_delay_seconds: float = 5.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    normalized_symbols = _normalize_symbols(symbols)
    if normalized_symbols != SYMBOLS:
        raise AlpacaOvernightProbeError(
            "The overnight proof requires the fixed SPY, QQQ, NVDA symbol set."
        )
    repository = credentials or AlpacaPaperCredentialRepository(
        lane=AlpacaPaperLane.CANARY_REALISTIC
    )
    if repository.lane is not AlpacaPaperLane.CANARY_REALISTIC:
        raise AlpacaOvernightProbeError(
            "The overnight proof requires the Canary-realistic Paper credential slot."
        )
    secret = repository.load()
    client = transport or AlpacaOvernightTransport()
    observed_start = _utc(now or datetime.now(UTC))
    session_start, session_end = _current_overnight_window(observed_start)
    if not (session_start <= observed_start < session_end):
        raise AlpacaOvernightProbeError(
            "The live overnight proof must run during the Sunday-through-Friday overnight session."
        )

    requests_evidence: list[dict[str, object]] = []
    parsed_latest: dict[str, dict[str, dict[str, object]]] = {}
    symbol_csv = ",".join(normalized_symbols)
    for feed in LATEST_FEEDS:
        parsed_latest[feed] = {}
        for data_type, path in LATEST_PATHS.items():
            observation, payload = client.get(
                path,
                params={"symbols": symbol_csv, "feed": feed, "currency": "USD"},
                credentials=secret,
                feed=feed,
                data_type=data_type,
            )
            parsed = _parse_latest_payload(
                data_type,
                payload,
                symbols=normalized_symbols,
                receipt=_parse_timestamp(str(observation["responseReceipt"])),
                feed=feed,
            )
            observation["records"] = parsed
            requests_evidence.append(observation)
            parsed_latest[feed][data_type] = parsed

    first_latest_bars = parsed_latest["overnight"].get("latestBar", {})
    if repeat_delay_seconds > 0:
        sleeper(repeat_delay_seconds)
    repeat_observation, repeat_payload = client.get(
        LATEST_PATHS["latestBar"],
        params={"symbols": symbol_csv, "feed": "overnight", "currency": "USD"},
        credentials=secret,
        feed="overnight",
        data_type="latestBarRepeat",
    )
    repeat_bars = _parse_latest_payload(
        "latestBar",
        repeat_payload,
        symbols=normalized_symbols,
        receipt=_parse_timestamp(str(repeat_observation["responseReceipt"])),
        feed="overnight",
    )
    repeat_observation["records"] = repeat_bars
    requests_evidence.append(repeat_observation)

    historical: dict[str, dict[str, object]] = {}
    historical_end = observed_start - timedelta(minutes=16)
    for symbol in normalized_symbols:
        if historical_end <= session_start:
            historical[symbol] = _empty_history("DELAY_WINDOW_NOT_REACHED")
            continue
        path = f"/v2/stocks/{symbol}/bars"
        observation, payload = client.get(
            path,
            params={
                "timeframe": "1Min",
                "start": session_start.isoformat(),
                "end": historical_end.isoformat(),
                "feed": "boats",
                "adjustment": "raw",
                "sort": "asc",
                "limit": 1000,
            },
            credentials=secret,
            feed="boats",
            data_type="historicalBars",
        )
        bars = _parse_historical_bars(payload, symbol=symbol)
        analysis = analyze_bars(bars, receipt=_parse_timestamp(str(observation["responseReceipt"])))
        observation["records"] = bars
        observation["analysis"] = analysis
        requests_evidence.append(observation)
        historical[symbol] = analysis

    provisional = compare_bar_observations(first_latest_bars, repeat_bars)
    observed_end = _utc(client.clock())
    result = {
        "schemaVersion": PROBE_SCHEMA,
        "mode": PROBE_MODE,
        "provider": "Alpaca Market Data",
        "endpoint": ALPACA_MARKET_DATA_BASE_URL,
        "credentialLane": AlpacaPaperLane.CANARY_REALISTIC.value,
        "symbols": list(normalized_symbols),
        "observationWindow": {
            "startedAt": observed_start.isoformat(),
            "completedAt": observed_end.isoformat(),
            "overnightSessionStart": session_start.isoformat(),
            "overnightSessionEnd": session_end.isoformat(),
        },
        "requests": requests_evidence,
        "historicalBars": historical,
        "currentMinuteObservation": provisional,
        "adjudication": adjudicate_probe(
            symbols=normalized_symbols,
            latest=parsed_latest,
            history=historical,
        ),
        "productionPersistence": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "mutatingRequestAttempted": False,
        "liveEndpointReachable": False,
        "executionAuthority": "UNVERIFIED",
        "canonicalStrategyAuthority": "NOT_GRANTED",
        "credentialsIncluded": False,
    }
    result["evidenceFingerprint"] = _fingerprint(result)
    _assert_sanitized(result, secret)
    return result


def analyze_bars(
    bars: Sequence[Mapping[str, object]],
    *,
    receipt: datetime,
) -> dict[str, object]:
    ordered = sorted(bars, key=lambda item: str(item.get("timestamp", "")))
    timestamps = [
        _parse_timestamp(str(item["timestamp"]))
        for item in ordered
        if item.get("timestamp")
    ]
    duplicates = len(timestamps) - len(set(timestamps))
    unique = sorted(set(timestamps))
    missing: list[str] = []
    for previous, current in zip(unique, unique[1:]):
        cursor = previous + timedelta(minutes=1)
        while cursor < current:
            missing.append(cursor.isoformat())
            cursor += timedelta(minutes=1)
    highs = [_number(item.get("high")) for item in ordered]
    lows = [_number(item.get("low")) for item in ordered]
    volumes = [_number(item.get("volume")) for item in ordered]
    latest = unique[-1] if unique else None
    return {
        "barCount": len(ordered),
        "bars": list(ordered),
        "firstMinute": unique[0].isoformat() if unique else None,
        "latestMinute": latest.isoformat() if latest else None,
        "latestAgeSeconds": _age_seconds(latest, receipt),
        "overnightHigh": max((value for value in highs if value is not None), default=None),
        "overnightLow": min((value for value in lows if value is not None), default=None),
        "cumulativeVolume": sum(value for value in volumes if value is not None),
        "missingMinuteCount": len(missing),
        "missingMinutes": missing,
        "duplicateMinuteCount": duplicates,
        "zeroVolumeBarCount": sum(value == 0 for value in volumes if value is not None),
        "nextPageTokenPresent": False,
    }


def compare_bar_observations(
    first: Mapping[str, Mapping[str, object]],
    second: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    fields = ("open", "high", "low", "close", "volume")
    for symbol in SYMBOLS:
        before = first.get(symbol)
        after = second.get(symbol)
        state = "UNAVAILABLE"
        changed: list[str] = []
        if before and after:
            if before.get("providerTimestamp") != after.get("providerTimestamp"):
                state = "MINUTE_ROLLED"
            else:
                changed = [field for field in fields if before.get(field) != after.get(field)]
                state = "PROVISIONAL_CHANGED" if changed else "NO_REVISION_OBSERVED"
        result[symbol] = {"state": state, "changedFields": changed}
    return result


def adjudicate_probe(
    *,
    symbols: Sequence[str],
    latest: Mapping[str, Mapping[str, Mapping[str, object]]],
    history: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    overnight = latest.get("overnight", {})
    boats = latest.get("boats", {})
    overnight_bars = overnight.get("latestBar", {})
    quotes = overnight.get("latestQuote", {})
    trades = overnight.get("latestTrade", {})
    history_counts = [int(history.get(symbol, {}).get("barCount", 0)) for symbol in symbols]
    volume_values = [
        history.get(symbol, {}).get("cumulativeVolume") for symbol in symbols
    ]
    derived_available = bool(overnight_bars)
    boats_available = bool(boats.get("latestBar")) or any(history_counts)
    feed_identity = (
        "DERIVED_OVERNIGHT" if derived_available else "BOATS" if boats_available else "UNKNOWN"
    )
    candles_pass = all(symbol in overnight_bars for symbol in symbols) and all(
        value > 0 for value in history_counts
    )
    volume_status = (
        "PASS"
        if all(value is not None and float(value) > 0 for value in volume_values)
        else "PARTIAL"
        if any(value is not None for value in volume_values)
        else "FAIL"
    )
    quote_count = sum(symbol in quotes for symbol in symbols)
    trade_count = sum(symbol in trades for symbol in symbols)
    quote_status = "PASS" if quote_count == len(symbols) else "PARTIAL" if quote_count else "FAIL"
    useful = candles_pass and quote_count > 0
    limitations = []
    if feed_identity == "DERIVED_OVERNIGHT":
        limitations.append("Latest context uses Alpaca's derived overnight feed.")
    if any(history_counts):
        limitations.append("Historical BOATS evidence is delayed by provider plan semantics.")
    if trade_count < len(symbols):
        limitations.append("Latest overnight trades were incomplete or unavailable.")
    if any(int(history.get(symbol, {}).get("missingMinuteCount", 0)) for symbol in symbols):
        limitations.append("Sparse overnight sequences contain minutes without returned bars.")
    context = "USEFUL_WITH_LIMITATIONS" if useful else "NOT_USEFUL"
    return {
        "OVERNIGHT_DATA_AVAILABLE": "PASS" if derived_available or boats_available else "FAIL",
        "OVERNIGHT_1M_CANDLES": "PASS" if candles_pass else "FAIL",
        "OVERNIGHT_VOLUME": volume_status,
        "OVERNIGHT_QUOTES": quote_status,
        "OVERNIGHT_TRADES": "PASS" if trade_count == len(symbols) else "PARTIAL" if trade_count else "FAIL",
        "FEED_IDENTITY": feed_identity,
        "BOATS_EVIDENCE_AVAILABLE": boats_available,
        "CONTEXT_USEFULNESS": context,
        "EXECUTION_AUTHORITY": "UNVERIFIED",
        "CANONICAL_STRATEGY_AUTHORITY": "NOT_GRANTED",
        "limitations": limitations,
    }


def write_proof(
    result: Mapping[str, object],
    *,
    json_path: Path,
    markdown_path: Path,
) -> tuple[str, str]:
    if json_path.exists() or markdown_path.exists():
        raise AlpacaOvernightProbeError("The write-once overnight proof output already exists.")
    json_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    markdown_bytes = (_render_markdown(result) + "\n").encode("utf-8")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes(json_bytes)
    markdown_path.write_bytes(markdown_bytes)
    return hashlib.sha256(json_bytes).hexdigest().upper(), hashlib.sha256(markdown_bytes).hexdigest().upper()


def _parse_latest_payload(
    data_type: str,
    payload: object | None,
    *,
    symbols: Sequence[str],
    receipt: datetime,
    feed: str,
) -> dict[str, dict[str, object]]:
    if not isinstance(payload, Mapping):
        return {}
    container_key = {
        "latestBar": "bars",
        "latestQuote": "quotes",
        "latestTrade": "trades",
        "snapshot": "snapshots",
    }[data_type]
    container = payload.get(container_key)
    if data_type == "snapshot" and not isinstance(container, Mapping):
        container = payload
    if not isinstance(container, Mapping):
        return {}
    parsed: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        record = container.get(symbol)
        if not isinstance(record, Mapping):
            continue
        if data_type == "snapshot":
            parsed[symbol] = _parse_snapshot(record, receipt=receipt, feed=feed)
        else:
            parsed[symbol] = _parse_record(
                record, data_type=data_type, receipt=receipt, feed=feed
            )
    return parsed


def _parse_record(
    record: Mapping[str, object],
    *,
    data_type: str,
    receipt: datetime,
    feed: str,
) -> dict[str, object]:
    timestamp = _timestamp_value(record)
    common = {
        "providerTimestamp": timestamp.isoformat() if timestamp else None,
        "localReceiptTimestamp": receipt.isoformat(),
        "observedAgeSeconds": _age_seconds(timestamp, receipt),
        "sessionClassification": classify_session(timestamp),
        "latencyClassification": classify_latency(timestamp, receipt=receipt, feed=feed, data_type=data_type),
    }
    if data_type == "latestBar":
        common.update(_bar_fields(record))
    elif data_type == "latestQuote":
        common.update({"bid": _number(record.get("bp")), "ask": _number(record.get("ap")), "bidSize": _number(record.get("bs")), "askSize": _number(record.get("as"))})
    elif data_type == "latestTrade":
        common.update({"price": _number(record.get("p")), "size": _number(record.get("s"))})
    return common


def _parse_snapshot(
    record: Mapping[str, object],
    *,
    receipt: datetime,
    feed: str,
) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, data_type in (("minuteBar", "latestBar"), ("latestQuote", "latestQuote"), ("latestTrade", "latestTrade")):
        value = record.get(key)
        if isinstance(value, Mapping):
            output[key] = _parse_record(value, data_type=data_type, receipt=receipt, feed=feed)
    return output


def _parse_historical_bars(payload: object | None, *, symbol: str) -> list[dict[str, object]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("bars"), list):
        return []
    output: list[dict[str, object]] = []
    for record in payload["bars"]:
        if not isinstance(record, Mapping):
            continue
        timestamp = _timestamp_value(record)
        if timestamp is None:
            continue
        bar = {"symbol": symbol, "timestamp": timestamp.isoformat(), "sessionClassification": classify_session(timestamp)}
        bar.update(_bar_fields(record))
        output.append(bar)
    return output


def _bar_fields(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "open": _number(record.get("o")),
        "high": _number(record.get("h")),
        "low": _number(record.get("l")),
        "close": _number(record.get("c")),
        "volume": _number(record.get("v")),
        "tradeCount": _number(record.get("n")),
        "vwap": _number(record.get("vw")),
    }


def classify_session(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "UNAVAILABLE"
    eastern = _utc(timestamp).astimezone(EASTERN)
    value = eastern.timetz().replace(tzinfo=None)
    weekday = eastern.weekday()
    if (weekday == 6 and value >= wall_time(20, 0)) or (weekday < 5 and value < wall_time(4, 0)):
        return "OVERNIGHT"
    if weekday < 5 and wall_time(4, 0) <= value < wall_time(9, 30):
        return "PREMARKET"
    if weekday < 5 and wall_time(9, 30) <= value < wall_time(16, 0):
        return "REGULAR"
    if weekday < 5 and wall_time(16, 0) <= value < wall_time(20, 0):
        return "AFTER_HOURS"
    return "CLOSED"


def classify_latency(
    timestamp: datetime | None,
    *,
    receipt: datetime,
    feed: str,
    data_type: str,
) -> str:
    if timestamp is None:
        return "UNAVAILABLE"
    if classify_session(timestamp) != "OVERNIGHT":
        return "STALE"
    if feed == "boats" or data_type == "latestTrade":
        return "DELAYED_CONTEXT"
    observed_age = _age_seconds(timestamp, receipt)
    if observed_age is None or observed_age < -5:
        return "STALE"
    if data_type == "latestQuote":
        return "FRESH_CONTEXT" if observed_age <= 10 else "DELAYED_CONTEXT"
    if data_type == "latestBar":
        return "FRESH_CONTEXT" if observed_age <= 120 else "DELAYED_CONTEXT"
    return "DELAYED_CONTEXT"


def _current_overnight_window(now: datetime) -> tuple[datetime, datetime]:
    eastern = _utc(now).astimezone(EASTERN)
    if eastern.timetz().replace(tzinfo=None) >= wall_time(20, 0):
        start = eastern.replace(hour=20, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=1)).replace(hour=4)
    else:
        end = eastern.replace(hour=4, minute=0, second=0, microsecond=0)
        start = (end - timedelta(days=1)).replace(hour=20)
    return start.astimezone(UTC), end.astimezone(UTC)


def _empty_history(reason: str) -> dict[str, object]:
    return {
        "barCount": 0,
        "bars": [],
        "firstMinute": None,
        "latestMinute": None,
        "latestAgeSeconds": None,
        "overnightHigh": None,
        "overnightLow": None,
        "cumulativeVolume": None,
        "missingMinuteCount": 0,
        "missingMinutes": [],
        "duplicateMinuteCount": 0,
        "zeroVolumeBarCount": 0,
        "reason": reason,
    }


def _require_market_data_endpoint(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname != ALPACA_MARKET_DATA_HOST or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise AlpacaOvernightEndpointError(
            "The overnight probe requires the exact Alpaca market-data HTTPS host."
        )


def _require_allowed_path(path: str) -> None:
    if path in LATEST_PATHS.values() or HISTORICAL_BAR_PATH.fullmatch(path):
        return
    raise AlpacaOvernightEndpointError("The overnight probe refused a non-market-data path.")


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    values = tuple(str(symbol).strip().upper() for symbol in symbols)
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", value) for value in values):
        raise AlpacaOvernightProbeError("The overnight probe received an invalid symbol.")
    return values


def _symbols_from_params(params: Mapping[str, object], path: str) -> tuple[str, ...]:
    if "symbols" in params:
        return tuple(str(params["symbols"]).split(","))
    match = re.fullmatch(r"/v2/stocks/([^/]+)/bars", path)
    return (match.group(1),) if match else ()


def _provider_error(payload: object | None, status: int, credentials: AlpacaPaperCredentials) -> str:
    message = ""
    if isinstance(payload, Mapping):
        message = str(payload.get("message") or payload.get("error") or "")
    safe = _sanitize_text(message, credentials)
    return f"HTTP_{status}" + (f":{safe}" if safe else "")


def _sanitize_text(value: str, credentials: AlpacaPaperCredentials) -> str:
    sanitized = value.replace(credentials.key_id, "[redacted]").replace(credentials.secret_key, "[redacted]")
    sanitized = re.sub(r"(?i)(api[_ -]?key|secret|token|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", sanitized)
    return sanitized[:300]


def _assert_sanitized(result: Mapping[str, object], credentials: AlpacaPaperCredentials) -> None:
    rendered = json.dumps(result, sort_keys=True)
    if credentials.key_id in rendered or credentials.secret_key in rendered:
        raise AlpacaOvernightProbeError("The overnight proof failed credential sanitation.")


def _timestamp_value(record: Mapping[str, object]) -> datetime | None:
    raw = record.get("t") or record.get("timestamp")
    return _parse_timestamp(str(raw)) if raw else None


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _age_seconds(timestamp: datetime | None, receipt: datetime) -> float | None:
    if timestamp is None:
        return None
    return round((_utc(receipt) - _utc(timestamp)).total_seconds(), 6)


def _number(value: object) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _fingerprint(result: Mapping[str, object]) -> str:
    payload = dict(result)
    payload.pop("evidenceFingerprint", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _render_markdown(result: Mapping[str, object]) -> str:
    adjudication = result["adjudication"]
    lines = [
        "# ARGUS-OVERNIGHT-001 Sunday-Night Capability Proof",
        "",
        "> Read-only context research. No account, position, order, Shadow, strategy, or production-store action occurred.",
        "",
        f"- Observation: `{result['observationWindow']['startedAt']}` to `{result['observationWindow']['completedAt']}`",
        f"- Symbols: `{', '.join(result['symbols'])}`",
        f"- Feed identity: `{adjudication['FEED_IDENTITY']}`",
        f"- Context usefulness: `{adjudication['CONTEXT_USEFULNESS']}`",
        f"- Execution authority: `{result['executionAuthority']}`",
        f"- Canonical strategy authority: `{result['canonicalStrategyAuthority']}`",
        "",
        "## Capability Adjudication",
        "",
    ]
    for key, value in adjudication.items():
        if key != "limitations":
            lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Historical Overnight Bars", "", "| Symbol | Bars | First | Latest | Age (s) | High | Low | Volume | Missing | Duplicates |", "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for symbol, evidence in result["historicalBars"].items():
        lines.append(
            f"| {symbol} | {evidence['barCount']} | {evidence['firstMinute'] or '-'} | {evidence['latestMinute'] or '-'} | {evidence['latestAgeSeconds'] if evidence['latestAgeSeconds'] is not None else '-'} | {evidence['overnightHigh'] if evidence['overnightHigh'] is not None else '-'} | {evidence['overnightLow'] if evidence['overnightLow'] is not None else '-'} | {evidence['cumulativeVolume'] if evidence['cumulativeVolume'] is not None else '-'} | {evidence['missingMinuteCount']} | {evidence['duplicateMinuteCount']} |"
        )
    lines.extend(["", "## Limitations", ""])
    for item in adjudication["limitations"]:
        lines.append(f"- {item}")
    lines.extend(["", f"Evidence fingerprint: `{result['evidenceFingerprint']}`"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(description="Run the read-only Alpaca overnight market-data probe.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeat-delay-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    result = run_probe(repeat_delay_seconds=args.repeat_delay_seconds)
    json_path = args.output_dir / "ARGUS-OVERNIGHT-001-sunday-night-proof.json"
    markdown_path = args.output_dir / "ARGUS-OVERNIGHT-001-sunday-night-proof.md"
    json_hash, markdown_hash = write_proof(result, json_path=json_path, markdown_path=markdown_path)
    print(json.dumps({"classification": result["adjudication"]["CONTEXT_USEFULNESS"], "jsonPath": str(json_path), "jsonSha256": json_hash, "markdownPath": str(markdown_path), "markdownSha256": markdown_hash, "credentialsIncluded": False, "accountRequested": False, "positionsRequested": False, "ordersRequested": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
