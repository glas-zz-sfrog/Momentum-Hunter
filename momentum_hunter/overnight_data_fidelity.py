from __future__ import annotations

"""Isolated, read-only market-phase fidelity sidecar.

The module deliberately has no broker, account, position, order, scheduler, or
production-persistence capability. It writes only caller-selected research
evidence and keeps provider feeds separate.
"""

import argparse
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.alpaca_overnight_probe import (
    LATEST_PATHS,
    AlpacaOvernightTransport,
    _parse_latest_payload,
)
from momentum_hunter.alpaca_paper_onboarding import (
    AlpacaPaperCredentialRepository,
    AlpacaPaperCredentials,
    AlpacaPaperLane,
)
from momentum_hunter.models import INSTITUTIONAL_MOMENTUM
from momentum_hunter.providers import FinvizProvider
from momentum_hunter.schwab_candle_contract import parse_price_history_response
from momentum_hunter.schwab_candle_observer import SchwabCandleHttpTransport
from momentum_hunter.schwab_market_data import SchwabMarketDataTransport
from momentum_hunter.schwab_onboarding import SchwabOAuthSecretRepository


TASK_ID = "ARGUS-OVERNIGHT-DATA-FIDELITY-001"
SCHEMA_VERSION = 1
MODE = "ISOLATED_READ_ONLY_MARKET_DATA_SIDECAR"
CANONICAL_BASE_SHA = "e1ea386f4640686569e2fb5a9a88e261ac974da3"
FIXED_SYMBOLS = ("SPY", "QQQ", "AAPL", "NVDA", "MU")
SCHWAB_SYMBOLS = ("SPY", "QQQ", "NVDA")
HOT_SET_SYMBOLS = (
    "SPY", "QQQ", "AAPL", "NVDA", "MU", "MSFT", "AMZN", "META", "GOOGL",
    "TSLA", "AMD", "AVGO", "NFLX", "PLTR", "INTC", "SMCI", "ARM", "QCOM",
    "TSM", "ASML", "JPM", "BAC", "XOM", "CVX", "WMT", "COST", "LLY",
    "UNH", "IWM", "DIA", "SOXX",
)
UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
ALPACA_STREAM_URL = "wss://stream.data.alpaca.markets/v1beta1/overnight"
ALLOWED_ROLES = {
    "DISCOVERY_RADAR",
    "CANONICAL_CANDIDATE",
    "DELAYED_RECONSTRUCTION",
    "INDICATIVE_ONLY",
    "UNUSABLE",
}
FORBIDDEN_ROUTE_TERMS = ("/account", "/positions", "/orders", "/preview")
FORBIDDEN_EVIDENCE_TERMS = (
    '"access_token"',
    '"refresh_token"',
    '"client_secret"',
    '"secret_key"',
    '"api_key"',
    '"accountnumber"',
    '"account_hash"',
    '"authorization"',
)


class OvernightDataFidelityError(RuntimeError):
    pass


def classify_phase(observed_at: datetime) -> str:
    eastern = _aware(observed_at).astimezone(EASTERN)
    clock = eastern.timetz().replace(tzinfo=None)
    if clock >= wall_time(20, 0) or clock < wall_time(4, 0):
        return "OVERNIGHT"
    if clock < wall_time(7, 0):
        return "EARLY_PREMARKET"
    if clock < wall_time(9, 30):
        return "STANDARD_PREMARKET"
    if clock < wall_time(16, 0):
        return "REGULAR"
    return "AFTER_HOURS"


def session_window(observed_at: datetime) -> tuple[datetime, datetime]:
    eastern = _aware(observed_at).astimezone(EASTERN)
    phase = classify_phase(eastern)
    day = eastern.date()
    if phase == "OVERNIGHT":
        start_day = day if eastern.time() >= wall_time(20, 0) else day - timedelta(days=1)
        start = datetime.combine(start_day, wall_time(20, 0), EASTERN)
    elif phase == "EARLY_PREMARKET":
        start = datetime.combine(day, wall_time(4, 0), EASTERN)
    elif phase == "STANDARD_PREMARKET":
        start = datetime.combine(day, wall_time(4, 0), EASTERN)
    elif phase == "REGULAR":
        start = datetime.combine(day, wall_time(9, 30), EASTERN)
    else:
        start = datetime.combine(day, wall_time(16, 0), EASTERN)
    return start.astimezone(UTC), eastern.astimezone(UTC)


def alpaca_feed_for_phase(phase: str) -> str:
    return "overnight" if phase == "OVERNIGHT" else "iex"


def provider_role(*, provider: str, feed: str, data_type: str, result: str) -> str:
    if result != "SUCCESS":
        return "UNUSABLE"
    if provider == "ALPACA" and feed == "overnight":
        return "INDICATIVE_ONLY" if data_type in {"latestQuote", "latestBar", "snapshot"} else "DELAYED_RECONSTRUCTION"
    if provider == "ALPACA" and feed == "boats":
        return "DELAYED_RECONSTRUCTION"
    if provider == "ALPACA" and feed == "iex":
        return "DISCOVERY_RADAR"
    if provider == "SCHWAB" and data_type in {"quotes", "priceHistory"}:
        return "CANONICAL_CANDIDATE"
    if provider == "FINVIZ":
        return "DISCOVERY_RADAR"
    return "UNUSABLE"


def run_checkpoint(
    *,
    checkpoint_code: str,
    observed_at: datetime | None = None,
    symbols: Sequence[str] = FIXED_SYMBOLS,
    include_capacity: bool = False,
    include_websocket: bool = False,
    probe_overnight_history: bool = False,
    include_finviz: bool | None = None,
    universe_source: Path | None = None,
    alpaca_repository: AlpacaPaperCredentialRepository | None = None,
    alpaca_transport: AlpacaOvernightTransport | None = None,
    schwab_repository: SchwabOAuthSecretRepository | None = None,
    schwab_quote_transport: SchwabMarketDataTransport | None = None,
    schwab_history_transport: SchwabCandleHttpTransport | None = None,
    finviz_provider: FinvizProvider | None = None,
    websocket_runner: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object]:
    started = _aware(observed_at or datetime.now(UTC))
    normalized = _normalize_symbols(symbols)
    if normalized[: len(FIXED_SYMBOLS)] != FIXED_SYMBOLS:
        raise OvernightDataFidelityError("The required fixed basket was not preserved in order.")
    phase = classify_phase(started)
    alpaca = run_alpaca_observation(
        observed_at=started,
        symbols=normalized,
        include_capacity=include_capacity,
        include_websocket=include_websocket,
        probe_overnight_history=probe_overnight_history,
        universe_source=universe_source,
        repository=alpaca_repository,
        transport=alpaca_transport,
        websocket_runner=websocket_runner,
    )
    schwab = run_schwab_observation(
        observed_at=started,
        repository=schwab_repository,
        quote_transport=schwab_quote_transport,
        history_transport=schwab_history_transport,
    )
    should_run_finviz = include_finviz if include_finviz is not None else phase != "OVERNIGHT"
    finviz = (
        run_finviz_observation(provider=finviz_provider)
        if should_run_finviz
        else {"status": "NOT_RUN_OUTSIDE_FINVIZ_EXTENDED_WINDOW", "role": "UNUSABLE"}
    )
    completed = datetime.now(UTC)
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": TASK_ID,
        "mode": MODE,
        "checkpointCode": _checkpoint_code(checkpoint_code),
        "runtimeIdentity": "overnight-data-fidelity-sidecar-v1",
        "sourceIdentity": {
            "canonicalBaseSha": CANONICAL_BASE_SHA,
            "moduleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
            "modulePathIncluded": False,
        },
        "observationWindow": {
            "startedAt": started.isoformat(),
            "completedAt": completed.isoformat(),
            "startedEastern": started.astimezone(EASTERN).isoformat(),
            "phase": phase,
            "elapsedMilliseconds": int((completed - started).total_seconds() * 1000),
        },
        "symbols": list(normalized),
        "providers": {"alpaca": alpaca, "schwab": schwab, "finviz": finviz},
        "authority": {
            "strategyAuthorityGranted": False,
            "executionAuthorityGranted": False,
            "providerAuthorityPromoted": False,
            "sourcesBlended": False,
        },
        "safety": _safety_evidence(),
    }
    result["evidenceFingerprint"] = fingerprint(result)
    require_sanitized(result, forbidden_values=())
    return result


def run_alpaca_observation(
    *,
    observed_at: datetime,
    symbols: Sequence[str],
    include_capacity: bool,
    include_websocket: bool,
    probe_overnight_history: bool,
    universe_source: Path | None,
    repository: AlpacaPaperCredentialRepository | None,
    transport: AlpacaOvernightTransport | None,
    websocket_runner: Callable[..., Mapping[str, object]] | None,
) -> dict[str, object]:
    repo = repository or AlpacaPaperCredentialRepository(lane=AlpacaPaperLane.CANARY_REALISTIC)
    if repo.lane is not AlpacaPaperLane.CANARY_REALISTIC:
        raise OvernightDataFidelityError("Only the existing Canary-realistic credential slot is allowed.")
    credentials = repo.load()
    client = transport or AlpacaOvernightTransport()
    phase = classify_phase(observed_at)
    current_feed = alpaca_feed_for_phase(phase)
    feeds = (current_feed, "boats") if phase == "OVERNIGHT" else (current_feed,)
    requests: list[dict[str, object]] = []
    latest: dict[str, object] = {}
    csv = ",".join(symbols)
    for feed in feeds:
        feed_latest: dict[str, object] = {}
        for data_type, path in LATEST_PATHS.items():
            observation, payload = client.get(
                path,
                params={"symbols": csv, "feed": feed, "currency": "USD"},
                credentials=credentials,
                feed=feed,
                data_type=data_type,
            )
            records = _parse_latest_payload(
                data_type,
                payload,
                symbols=symbols,
                receipt=_timestamp(str(observation["responseReceipt"])),
                feed=feed,
            )
            observation["recordCount"] = len(records)
            observation["returnedSymbols"] = sorted(records)
            observation["role"] = provider_role(
                provider="ALPACA", feed=feed, data_type=data_type, result=str(observation["apiResult"])
            )
            requests.append(observation)
            feed_latest[data_type] = records
        latest[feed] = feed_latest

    window_start, window_end = session_window(observed_at)
    history: dict[str, object] = {}
    history_feeds = feeds if phase != "OVERNIGHT" or probe_overnight_history else ("boats",)
    if phase == "OVERNIGHT" and not probe_overnight_history:
        history["overnight"] = {
            "status": "NOT_REPEATED_AFTER_LIVE_INVALID_FEED_PROOF",
            "role": "UNUSABLE",
        }
    for feed in history_feeds:
        history_end = window_end - timedelta(minutes=16) if feed == "boats" else window_end
        feed_history: dict[str, object] = {}
        for symbol in symbols:
            symbol_history: dict[str, object] = {}
            for family, suffix in (("bars", "bars"), ("quotes", "quotes"), ("trades", "trades")):
                if history_end <= window_start:
                    symbol_history[family] = {"status": "DELAY_WINDOW_NOT_REACHED", "recordCount": 0}
                    continue
                observation, payload = client.get(
                    f"/v2/stocks/{symbol}/{suffix}",
                    params={
                        "start": window_start.isoformat(),
                        "end": history_end.isoformat(),
                        "feed": feed,
                        "sort": "asc",
                        "limit": 10_000,
                        **({"timeframe": "1Min", "adjustment": "raw"} if family == "bars" else {}),
                    },
                    credentials=credentials,
                    feed=feed,
                    data_type=f"historical{family.title()}",
                )
                rows = _historical_rows(payload, family)
                summary = summarize_history(rows, family=family)
                summary["status"] = str(observation["apiResult"])
                summary["nextPageTokenPresent"] = bool(
                    isinstance(payload, Mapping) and payload.get("next_page_token")
                )
                summary["role"] = provider_role(
                    provider="ALPACA", feed=feed, data_type=f"historical{family.title()}", result=str(observation["apiResult"])
                )
                symbol_history[family] = summary
                observation["recordCount"] = len(rows)
                observation["role"] = summary["role"]
                requests.append(observation)
            feed_history[symbol] = symbol_history
        history[feed] = feed_history

    capacity = (
        measure_alpaca_rest_capacity(
            client=client,
            credentials=credentials,
            feed=current_feed,
            universe_source=universe_source,
        )
        if include_capacity
        else {"status": "NOT_RUN_AT_THIS_CHECKPOINT"}
    )
    stream = (
        dict((websocket_runner or run_alpaca_websocket_matrix)(credentials=credentials))
        if include_websocket
        else {"status": "NOT_RUN_AT_THIS_CHECKPOINT"}
    )
    result = {
        "provider": "ALPACA",
        "planDetected": "BASIC_BY_OBSERVED_ENTITLEMENT_AND_LOCAL_CONFIGURATION",
        "endpointHost": "data.alpaca.markets",
        "currentFeed": current_feed,
        "latest": latest,
        "history": history,
        "requests": requests,
        "capacity": capacity,
        "websocket": stream,
        "assetEligibility": {
            "status": "NOT_QUERIED_MARKET_DATA_ONLY_BOUNDARY",
            "reason": "Alpaca asset metadata is outside the allowed market-data-only host for this task.",
        },
        "credentialsIncluded": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }
    require_sanitized(result, forbidden_values=(credentials.key_id, credentials.secret_key))
    return result


def measure_alpaca_rest_capacity(
    *,
    client: AlpacaOvernightTransport,
    credentials: AlpacaPaperCredentials,
    feed: str,
    universe_source: Path | None,
) -> dict[str, object]:
    universe, source = load_symbol_universe(universe_source)
    measurements: list[dict[str, object]] = []
    for requested_size in (30, 100, min(500, len(universe))):
        if requested_size < 1 or any(row["requestedSymbolCount"] == requested_size for row in measurements):
            continue
        symbols = tuple(universe[:requested_size])
        started = time.monotonic()
        observation, payload = client.get(
            LATEST_PATHS["snapshot"],
            params={"symbols": ",".join(symbols), "feed": feed, "currency": "USD"},
            credentials=credentials,
            feed=feed,
            data_type="capacitySnapshot",
        )
        elapsed = time.monotonic() - started
        returned = _snapshot_symbols(payload, symbols)
        measurements.append(
            {
                "requestedSymbolCount": len(symbols),
                "returnedSymbolCount": len(returned),
                "missingSymbolCount": len(set(symbols) - set(returned)),
                "httpResult": observation["apiResult"],
                "apiStatus": observation["apiStatus"],
                "elapsedMilliseconds": int(elapsed * 1000),
                "requestCount": 1,
                "role": provider_role(provider="ALPACA", feed=feed, data_type="snapshot", result=str(observation["apiResult"])),
            }
        )
    accepted_maximum = max(
        (int(item["requestedSymbolCount"]) for item in measurements if item["httpResult"] == "SUCCESS"),
        default=0,
    )
    covered_maximum = max(
        (
            int(item["requestedSymbolCount"])
            for item in measurements
            if item["httpResult"] == "SUCCESS" and int(item["returnedSymbolCount"]) > 0
        ),
        default=0,
    )
    return {
        "status": "MEASURED",
        "feed": feed,
        "universeSource": source,
        "availableUniverseSize": len(universe),
        "measurements": measurements,
        "largestAcceptedSingleRequest": accepted_maximum,
        "largestSuccessfulCoverageRequest": covered_maximum,
        "officialBasicRestLimitCallsPerMinute": 200,
        "requestBudgetPulses": {
            "perMinute": 200 if covered_maximum else 0,
            "perFiveMinutes": 1000 if covered_maximum else 0,
            "perTenMinutes": 2000 if covered_maximum else 0,
            "basis": "OFFICIAL_200_CALLS_PER_MINUTE_DIVIDED_BY_ONE_MEASURED_REQUEST_PER_PULSE",
            "networkConcurrencyOrProviderFairUseClaimed": False,
        },
        "strategyAuthorityGranted": False,
    }


def load_symbol_universe(source: Path | None) -> tuple[tuple[str, ...], dict[str, object]]:
    if source is None:
        return HOT_SET_SYMBOLS, {"kind": "BUILT_IN_LIQUID_TEST_SET", "sha256": fingerprint({"symbols": HOT_SET_SYMBOLS})}
    path = source.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, list):
        raise OvernightDataFidelityError("The research universe source had an invalid shape.")
    symbols = sorted(
        {
            str(row.get("symbol", "")).strip().upper()
            for row in records
            if isinstance(row, Mapping) and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", str(row.get("symbol", "")).strip().upper())
        }
    )
    if len(symbols) < 30:
        raise OvernightDataFidelityError("The research universe source did not contain 30 valid symbols.")
    return tuple(symbols), {
        "kind": "READ_ONLY_EXISTING_RESEARCH_SYMBOL_UNIVERSE",
        "pathIncluded": False,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


def run_alpaca_websocket_probe(
    *,
    credentials: AlpacaPaperCredentials,
    symbols: Sequence[str] = HOT_SET_SYMBOLS[:30],
    duration_seconds: float = 8.0,
    families: Sequence[str] = ("bars", "quotes", "trades"),
) -> dict[str, object]:
    normalized = _normalize_symbols(symbols)
    if len(normalized) > 30:
        raise OvernightDataFidelityError("The Basic websocket proof is bounded to 30 symbols.")
    requested_families = tuple(dict.fromkeys(str(value).strip().lower() for value in families))
    if not requested_families or any(value not in {"bars", "quotes", "trades"} for value in requested_families):
        raise OvernightDataFidelityError("The websocket proof received an invalid market-data family.")
    try:
        import websocket
    except ImportError as exc:
        raise OvernightDataFidelityError("websocket-client is unavailable.") from exc
    started = datetime.now(UTC)
    socket = None
    counts: dict[str, int] = {}
    observed_symbols: set[str] = set()
    schema_keys: dict[str, list[str]] = {}
    authenticated = False
    subscribed = False
    subscription_control: list[dict[str, object]] = []
    error_type: str | None = None
    try:
        socket = websocket.create_connection(ALPACA_STREAM_URL, timeout=5, enable_multithread=True)
        _receive_websocket_json(socket)
        socket.send(json.dumps({"action": "auth", "key": credentials.key_id, "secret": credentials.secret_key}))
        auth = _receive_websocket_json(socket)
        authenticated = _websocket_success(auth, "authenticated")
        if not authenticated:
            raise OvernightDataFidelityError("Alpaca market-data websocket authentication failed safely.")
        request = {"action": "subscribe"}
        request.update({family: list(normalized) for family in requested_families})
        socket.send(json.dumps(request))
        subscription = _receive_websocket_json(socket)
        subscription_control = _summarize_websocket_control(subscription)
        subscribed = _websocket_subscription_ack(subscription, normalized, requested_families)
        deadline = time.monotonic() + max(1.0, min(30.0, duration_seconds))
        while time.monotonic() < deadline:
            socket.settimeout(max(0.1, min(1.0, deadline - time.monotonic())))
            try:
                messages = _receive_websocket_json(socket)
            except Exception as exc:
                if type(exc).__name__ in {"WebSocketTimeoutException", "TimeoutError"}:
                    continue
                raise
            for row in messages if isinstance(messages, list) else [messages]:
                if not isinstance(row, Mapping):
                    continue
                kind = str(row.get("T", "UNKNOWN"))
                counts[kind] = counts.get(kind, 0) + 1
                symbol = str(row.get("S", "")).strip().upper()
                if symbol in normalized:
                    observed_symbols.add(symbol)
                schema_keys.setdefault(kind, sorted(str(key) for key in row.keys()))
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        if socket is not None:
            socket.close()
    completed = datetime.now(UTC)
    result = {
        "status": "PASS" if authenticated and subscribed and error_type is None else "PARTIAL" if authenticated else "FAIL",
        "endpoint": ALPACA_STREAM_URL,
        "feed": "overnight",
        "requestedSymbolCount": len(normalized),
        "requestedFamilies": list(requested_families),
        "requestedSubscriptionCount": len(normalized) * len(requested_families),
        "observedSymbolCount": len(observed_symbols),
        "messageCounts": counts,
        "messageSchemaKeys": schema_keys,
        "authenticated": authenticated,
        "subscribed": subscribed,
        "subscriptionControl": subscription_control,
        "elapsedMilliseconds": int((completed - started).total_seconds() * 1000),
        "errorType": error_type,
        "credentialsIncluded": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }
    require_sanitized(result, forbidden_values=(credentials.key_id, credentials.secret_key))
    return result


def run_alpaca_websocket_matrix(*, credentials: AlpacaPaperCredentials) -> dict[str, object]:
    scenarios = (
        ("THIRTY_BARS", HOT_SET_SYMBOLS[:30], ("bars",)),
        ("FIFTEEN_BARS_QUOTES", HOT_SET_SYMBOLS[:15], ("bars", "quotes")),
        ("TEN_ALL_FAMILIES", HOT_SET_SYMBOLS[:10], ("bars", "quotes", "trades")),
    )
    results = []
    for name, symbols, families in scenarios:
        result = run_alpaca_websocket_probe(
            credentials=credentials,
            symbols=symbols,
            families=families,
            duration_seconds=5.0,
        )
        result["scenario"] = name
        results.append(result)
    passed = [result for result in results if result["status"] == "PASS"]
    return {
        "status": "PASS" if len(passed) == len(results) else "PARTIAL" if passed else "FAIL",
        "scenarios": results,
        "successfulScenarioCount": len(passed),
        "connectionCount": len(results),
        "reconnectSuccessfulCount": sum(bool(result["authenticated"]) for result in results),
        "credentialMaterialIncluded": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }


def run_schwab_observation(
    *,
    observed_at: datetime,
    repository: SchwabOAuthSecretRepository | None,
    quote_transport: SchwabMarketDataTransport | None,
    history_transport: SchwabCandleHttpTransport | None,
) -> dict[str, object]:
    repo = repository or SchwabOAuthSecretRepository()
    status = repo.status()
    if status.get("tokenState") != "ACTIVE":
        return {
            "provider": "SCHWAB",
            "status": "NOT_RUN_SHARED_TOKEN_NOT_ACTIVE",
            "tokenState": status.get("tokenState", "UNKNOWN"),
            "tokenRefreshAttempted": False,
            "reason": "The sidecar will not refresh or mutate the credential shared with production.",
            "streamer": "NOT_RUN_NO_ACCOUNT_BEARING_BOOTSTRAP",
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
    tokens = repo.load_tokens()
    quotes_client = quote_transport or SchwabMarketDataTransport()
    history_client = history_transport or SchwabCandleHttpTransport()
    started = datetime.now(UTC)
    try:
        batch = quotes_client.fetch_quotes_with_clock(tokens.access_token, SCHWAB_SYMBOLS)
        quotes = {
            symbol: {
                "symbol": symbol,
                "source": quote.source,
                "providerQuoteTimestamp": quote.provider_quote_timestamp,
                "providerBidTimestamp": quote.provider_bid_timestamp,
                "providerAskTimestamp": quote.provider_ask_timestamp,
                "bid": quote.bid,
                "ask": quote.ask,
                "last": quote.last,
                "volume": quote.volume,
                "realtime": quote.realtime,
                "securityStatus": quote.security_status,
                "role": "CANONICAL_CANDIDATE",
            }
            for symbol, quote in batch.quotes.items()
        }
        history: dict[str, object] = {}
        window_start = datetime.combine(
            observed_at.astimezone(EASTERN).date() - timedelta(days=1),
            wall_time(20, 0),
            EASTERN,
        ).astimezone(UTC)
        for symbol in SCHWAB_SYMBOLS:
            payload = history_client.fetch_price_history(
                tokens.access_token,
                symbol,
                start_at=window_start,
                end_at=observed_at,
                extended_hours=True,
            )
            candles = parse_price_history_response(payload, expected_symbol=symbol)
            rows = [candle.to_evidence() for candle in candles]
            history[symbol] = summarize_history(rows, family="bars") | {
                "earliestMinute": rows[0]["timestamp"] if rows else None,
                "latestMinute": rows[-1]["timestamp"] if rows else None,
                "role": "CANONICAL_CANDIDATE" if rows else "UNUSABLE",
            }
        result = {
            "provider": "SCHWAB",
            "status": "SUCCESS",
            "quotes": quotes,
            "quoteClockProof": batch.clock_skew_proof,
            "priceHistory": history,
            "streamer": "NOT_RUN_NO_ACCOUNT_BEARING_BOOTSTRAP",
            "tokenRefreshAttempted": False,
            "elapsedMilliseconds": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
    except Exception as exc:
        result = {
            "provider": "SCHWAB",
            "status": "FAILED_SAFE",
            "errorType": type(exc).__name__,
            "streamer": "NOT_RUN_NO_ACCOUNT_BEARING_BOOTSTRAP",
            "tokenRefreshAttempted": False,
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
    require_sanitized(result, forbidden_values=(tokens.access_token, tokens.refresh_token))
    return result


def run_finviz_observation(*, provider: FinvizProvider | None = None) -> dict[str, object]:
    client = provider or FinvizProvider(backoff_seconds=(), quote_backoff_seconds=())
    started = datetime.now(UTC)
    try:
        snapshot = client.discover(INSTITUTIONAL_MOMENTUM)
        diagnostics = client.last_scan_diagnostics
        qualifying = list(snapshot.qualified_candidates())
        result = {
            "provider": "FINVIZ",
            "status": "SUCCESS",
            "role": "DISCOVERY_RADAR",
            "requestedAt": started.isoformat(),
            "receivedAt": datetime.now(UTC).isoformat(),
            "rawRowCount": diagnostics.data_row_count if diagnostics else None,
            "parsedRowCount": diagnostics.parsed_row_count if diagnostics else None,
            "qualifyingRowCount": diagnostics.qualifying_candidate_count if diagnostics else None,
            "schemaFingerprint": diagnostics.schema_fingerprint if diagnostics else None,
            "semanticStatus": diagnostics.semantic_status if diagnostics else None,
            "qualifyingSymbols": [candidate.ticker for candidate in qualifying],
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
    except Exception as exc:
        result = {
            "provider": "FINVIZ",
            "status": "FAILED_SAFE",
            "role": "UNUSABLE",
            "errorType": type(exc).__name__,
            "requestedAt": started.isoformat(),
            "receivedAt": datetime.now(UTC).isoformat(),
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }
    require_sanitized(result, forbidden_values=())
    return result


def summarize_history(rows: Sequence[Mapping[str, object]], *, family: str) -> dict[str, object]:
    timestamps = []
    venues: set[str] = set()
    volumes: list[float] = []
    for row in rows:
        timestamp = _row_timestamp(row)
        if timestamp is not None:
            timestamps.append(timestamp)
        venue = row.get("x") or row.get("exchange")
        if venue:
            venues.add(str(venue))
        value = row.get("v") if "v" in row else row.get("volume")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            volumes.append(float(value))
    ordered = sorted(timestamps)
    duplicates = len(ordered) - len(set(ordered))
    return {
        "family": family,
        "recordCount": len(rows),
        "firstTimestamp": ordered[0].isoformat() if ordered else None,
        "latestTimestamp": ordered[-1].isoformat() if ordered else None,
        "duplicateTimestampCount": duplicates,
        "venueCodes": sorted(venues),
        "volumeTotal": round(sum(volumes), 6) if volumes else None,
    }


def fingerprint(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("evidenceFingerprint", None)
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest().upper()


def write_checkpoint(result: Mapping[str, object], *, output_root: Path) -> tuple[Path, Path, str, str]:
    root = output_root.expanduser().resolve()
    code = _checkpoint_code(str(result["checkpointCode"]))
    json_path = root / "checkpoints" / f"{code}.json"
    markdown_path = root / "checkpoints" / f"{code}.md"
    if json_path.exists() or markdown_path.exists():
        raise OvernightDataFidelityError("The write-once checkpoint already exists.")
    require_sanitized(result, forbidden_values=())
    json_bytes = (json.dumps(result, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    markdown_bytes = render_checkpoint_markdown(result).encode("utf-8")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_new(json_path, json_bytes)
    try:
        _write_new(markdown_path, markdown_bytes)
    except Exception:
        json_path.unlink(missing_ok=True)
        raise
    return (
        json_path,
        markdown_path,
        hashlib.sha256(json_bytes).hexdigest().upper(),
        hashlib.sha256(markdown_bytes).hexdigest().upper(),
    )


def load_and_verify_checkpoint(path: Path) -> dict[str, object]:
    result = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("taskId") != TASK_ID:
        raise OvernightDataFidelityError("The checkpoint identity is invalid.")
    if result.get("evidenceFingerprint") != fingerprint(result):
        raise OvernightDataFidelityError("The checkpoint fingerprint did not verify.")
    require_sanitized(result, forbidden_values=())
    return result


def render_checkpoint_markdown(result: Mapping[str, object]) -> str:
    providers = result["providers"]
    alpaca = providers["alpaca"]
    schwab = providers["schwab"]
    finviz = providers["finviz"]
    window = result["observationWindow"]
    return "\n".join(
        (
            f"# {TASK_ID} — {result['checkpointCode']}",
            "",
            f"- Phase: `{window['phase']}`",
            f"- Started ET: `{window['startedEastern']}`",
            f"- Alpaca feed: `{alpaca['currentFeed']}`",
            f"- Schwab: `{schwab['status']}`",
            f"- Finviz: `{finviz['status']}`",
            f"- Strategy authority: `NOT_GRANTED`",
            f"- Execution authority: `NOT_GRANTED`",
            f"- Account/position/order requests: `0 / 0 / 0`",
            "",
            "Provider evidence remains separate. No source was promoted, averaged, or voted into authority.",
            "",
        )
    )


def require_sanitized(value: Mapping[str, object], *, forbidden_values: Sequence[str]) -> None:
    rendered = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
    lowered = rendered.lower()
    if any(term in lowered for term in FORBIDDEN_EVIDENCE_TERMS):
        raise OvernightDataFidelityError("Evidence contains a forbidden credential-shaped field.")
    if any(secret and secret in rendered for secret in forbidden_values):
        raise OvernightDataFidelityError("Evidence contains credential material.")
    if any(route in lowered for route in FORBIDDEN_ROUTE_TERMS):
        raise OvernightDataFidelityError("Evidence contains a forbidden account/order route.")


def _historical_rows(payload: object | None, family: str) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get(family)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _mapping_keys(payload: object | None, key: str) -> tuple[str, ...]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get(key), Mapping):
        return ()
    return tuple(sorted(str(item).strip().upper() for item in payload[key]))


def _snapshot_symbols(payload: object | None, expected: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    nested = payload.get("snapshots")
    source = nested if isinstance(nested, Mapping) else payload
    allowed = set(expected)
    return tuple(
        sorted(
            symbol
            for key in source
            if (symbol := str(key).strip().upper()) in allowed
        )
    )


def _row_timestamp(row: Mapping[str, object]) -> datetime | None:
    value = row.get("t") or row.get("timestamp")
    if value is None:
        return None
    try:
        return _timestamp(str(value))
    except OvernightDataFidelityError:
        return None


def _receive_websocket_json(socket: object) -> object:
    raw = socket.recv()
    return json.loads(raw)


def _websocket_success(payload: object, expected: str) -> bool:
    rows = payload if isinstance(payload, list) else [payload]
    return any(
        isinstance(row, Mapping)
        and str(row.get("T", "")).lower() == "success"
        and expected.lower() in str(row.get("msg", "")).lower()
        for row in rows
    )


def _websocket_subscription_ack(
    payload: object,
    expected_symbols: Sequence[str],
    expected_families: Sequence[str] = ("bars", "quotes", "trades"),
) -> bool:
    expected = set(expected_symbols)
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("T", "")).lower() != "subscription":
            continue
        admitted_by_family: dict[str, set[str]] = {}
        for family in ("bars", "quotes", "trades"):
            values = row.get(family)
            if isinstance(values, list):
                admitted_by_family[family] = {
                    str(value).strip().upper() for value in values
                }
        if all(expected <= admitted_by_family.get(family, set()) for family in expected_families):
            return True
    return False


def _summarize_websocket_control(payload: object) -> list[dict[str, object]]:
    rows = payload if isinstance(payload, list) else [payload]
    result: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        summary: dict[str, object] = {
            "type": str(row.get("T", "UNKNOWN")),
            "code": row.get("code"),
            "message": str(row.get("msg", ""))[:240],
            "keys": sorted(str(key) for key in row.keys()),
        }
        for family in ("bars", "quotes", "trades"):
            values = row.get(family)
            summary[f"{family}Count"] = len(values) if isinstance(values, list) else None
        result.append(summary)
    return result


def _safety_evidence() -> dict[str, object]:
    return {
        "productionPersistence": False,
        "productionRuntimeChanged": False,
        "productionWriterChanged": False,
        "productionSchedulerChanged": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "paperMutation": False,
        "shadowMutation": False,
        "credentialMaterialIncluded": False,
        "orderCapability": "UNAVAILABLE",
    }


def _checkpoint_code(value: str) -> str:
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,63}", normalized):
        raise OvernightDataFidelityError("Checkpoint code is invalid.")
    return normalized


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    if not normalized or any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol) for symbol in normalized):
        raise OvernightDataFidelityError("A symbol was invalid.")
    return normalized


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise OvernightDataFidelityError("Provider timestamp was invalid.") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OvernightDataFidelityError("Aware timestamps are required.")
    return value.astimezone(UTC)


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one isolated overnight-data fidelity checkpoint.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--universe-source", type=Path)
    parser.add_argument("--capacity", action="store_true")
    parser.add_argument("--websocket", action="store_true")
    parser.add_argument("--probe-overnight-history", action="store_true")
    parser.add_argument("--finviz", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_checkpoint(
            checkpoint_code=args.checkpoint,
            include_capacity=args.capacity,
            include_websocket=args.websocket,
            probe_overnight_history=args.probe_overnight_history,
            include_finviz=args.finviz,
            universe_source=args.universe_source,
        )
        json_path, markdown_path, json_hash, markdown_hash = write_checkpoint(result, output_root=args.output_root)
        print(json.dumps({
            "classification": "CHECKPOINT_COMPLETED",
            "checkpoint": result["checkpointCode"],
            "phase": result["observationWindow"]["phase"],
            "jsonPath": str(json_path),
            "jsonSha256": json_hash,
            "markdownPath": str(markdown_path),
            "markdownSha256": markdown_hash,
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "classification": "CHECKPOINT_FAILED_SAFE",
            "errorType": type(exc).__name__,
            "credentialMaterialIncluded": False,
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
