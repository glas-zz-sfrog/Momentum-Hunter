from __future__ import annotations

"""Read-only Schwab quote boundary for nontransmitting Shadow evidence."""

import argparse
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import requests

from momentum_hunter.schwab_account_discovery import (
    SchwabAccountDiscoveryError,
)
from momentum_hunter.schwab_account_validation import (
    SchwabAccountValidationError,
)
from momentum_hunter.schwab_bound_account_refresh import (
    BOUND_REFRESH_CONFIRMATION,
    SchwabBoundAccountRefresh,
    SchwabBoundAccountRefreshError,
)
from momentum_hunter.schwab_onboarding import (
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import AccountIsolationError
from momentum_hunter.shadow_market_validity import (
    EASTERN_TZ,
    ShadowMarketValidityPolicy,
)
from momentum_hunter.shadow_opening import (
    build_https_clock_skew_proof,
    clock_skew_findings,
    trusted_clock_bounds,
)


SCHWAB_QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"
SCHWAB_QUOTE_SOURCE = "schwab_marketdata_v1_quotes:min_bid_ask_quote_time_v1"
HTTP_TIMEOUT = (5.0, 30.0)
MAX_QUOTE_RESPONSE_BYTES = 1024 * 1024
MAX_QUOTE_SYMBOLS = 500
REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION = 4
LIVE_SCHWAB_QUOTE_PROOF_ORIGIN = "LIVE_SCHWAB_TRADER_API"
INJECTED_QUOTE_PROOF_ORIGIN = "INJECTED_SOURCE"
UNSPECIFIED_QUOTE_PROOF_ORIGIN = "UNSPECIFIED_SOURCE"
SCHWAB_HTTPS_CLOCK_SOURCE = "schwab_marketdata_v1_quotes:https_date"


class SchwabMarketDataError(RuntimeError):
    pass


class SchwabMarketDataAuthorizationError(SchwabMarketDataError):
    pass


class SchwabMarketDataNetworkError(SchwabMarketDataError):
    pass


class SchwabMarketDataResponseError(SchwabMarketDataError):
    pass


class StoredSchwabAccessTokenProvider:
    def __init__(
        self,
        secrets_repository: SchwabOAuthSecretRepository,
    ) -> None:
        self.secrets = secrets_repository

    def access_token(self) -> str:
        try:
            tokens = self.secrets.load_tokens()
        except SchwabOAuthError as exc:
            raise SchwabMarketDataAuthorizationError(
                "Schwab market data could not load encrypted OAuth state."
            ) from exc
        if tokens.expired:
            raise SchwabMarketDataAuthorizationError(
                "Schwab market data access token is expired."
            )
        return tokens.access_token


class BoundSchwabAccessTokenProvider:
    """Refresh only through immutable single-CASH-account revalidation."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        bound_refresh: object | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        if bound_refresh is None:
            bound_refresh = SchwabBoundAccountRefresh(
                secrets_repository=self.secrets,
            )
        self.bound_refresh = bound_refresh

    def access_token(self) -> str:
        try:
            tokens = self.secrets.load_tokens()
            if not tokens.expired:
                return tokens.access_token
            self.bound_refresh.refresh(
                confirmation=BOUND_REFRESH_CONFIRMATION,
            )
            refreshed = self.secrets.load_tokens()
        except (
            AccountIsolationError,
            SchwabAccountDiscoveryError,
            SchwabAccountValidationError,
            SchwabBoundAccountRefreshError,
            SchwabOAuthError,
        ) as exc:
            raise SchwabMarketDataAuthorizationError(
                "Schwab market data OAuth refresh or bound-account revalidation failed safely."
            ) from exc
        if refreshed.expired:
            raise SchwabMarketDataAuthorizationError(
                "Schwab market data access token remained expired after guarded refresh."
            )
        return refreshed.access_token


@dataclass(frozen=True)
class SchwabExecutableQuote:
    symbol: str
    timestamp: str
    provider_quote_timestamp: str
    provider_bid_timestamp: str
    provider_ask_timestamp: str
    bid: float | None
    ask: float | None
    last: float | None
    volume: int | None
    session: str
    trading_state: str
    realtime: bool
    security_status: str
    source: str = SCHWAB_QUOTE_SOURCE

    def to_shadow_quote(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "provider_quote_timestamp": self.provider_quote_timestamp,
            "provider_bid_timestamp": self.provider_bid_timestamp,
            "provider_ask_timestamp": self.provider_ask_timestamp,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "volume": self.volume,
            "session": self.session,
            "trading_state": self.trading_state,
            "realtime": self.realtime,
            "security_status": self.security_status,
            "source": self.source,
        }


@dataclass(frozen=True)
class SchwabQuoteBatch:
    quotes: dict[str, SchwabExecutableQuote]
    clock_skew_proof: dict[str, object]


@dataclass(frozen=True)
class SchwabQuoteEvidenceBatch:
    quotes: dict[str, dict[str, object]]
    clock_skew_proof: dict[str, object]


class SchwabMarketDataTransport:
    """Exact-host GET transport for Schwab's versioned quote endpoint."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_quotes(
        self,
        access_token: str,
        symbols: Sequence[str],
    ) -> dict[str, SchwabExecutableQuote]:
        return self.fetch_quotes_with_clock(
            access_token,
            symbols,
        ).quotes

    def fetch_quotes_with_clock(
        self,
        access_token: str,
        symbols: Sequence[str],
    ) -> SchwabQuoteBatch:
        if not access_token.strip():
            raise SchwabMarketDataAuthorizationError(
                "Schwab market data requires an active OAuth access token."
            )
        normalized = normalize_symbols(symbols)
        if not normalized:
            now = self.clock()
            return SchwabQuoteBatch(
                quotes={},
                clock_skew_proof=build_https_clock_skew_proof(
                    request_started_at=now,
                    response_received_at=now,
                    remote_date_header="",
                    source_identity=SCHWAB_HTTPS_CLOCK_SOURCE,
                ),
            )
        request_started_at = self.clock()
        try:
            response = self.session.get(
                SCHWAB_QUOTES_URL,
                params={
                    "symbols": ",".join(normalized),
                    "fields": "quote",
                },
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabMarketDataNetworkError(
                "Schwab market data could not reach the exact configured endpoint."
            ) from None
        response_received_at = self.clock()
        if response.is_redirect:
            raise SchwabMarketDataResponseError(
                "Schwab market data refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise SchwabMarketDataResponseError(
                f"Schwab market data failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_QUOTE_RESPONSE_BYTES:
            raise SchwabMarketDataResponseError(
                "Schwab market data response exceeded the size limit."
            )
        try:
            payload = response.json()
        except ValueError:
            raise SchwabMarketDataResponseError(
                "Schwab market data response was not valid JSON."
            ) from None
        response_headers = getattr(response, "headers", {})
        remote_date_header = (
            str(response_headers.get("Date", ""))
            if isinstance(response_headers, Mapping)
            else ""
        )
        return SchwabQuoteBatch(
            quotes=parse_quote_response(
                payload,
                expected_symbols=normalized,
            ),
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=request_started_at,
                response_received_at=response_received_at,
                remote_date_header=remote_date_header,
                source_identity=SCHWAB_HTTPS_CLOCK_SOURCE,
            ),
        )


class SchwabMarketDataQuoteSource:
    """Quote source with guarded bound-account refresh and no order capability."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        transport: SchwabMarketDataTransport | None = None,
        token_provider: object | None = None,
    ) -> None:
        if token_provider is not None and secrets_repository is not None:
            raise ValueError(
                "Provide either a token provider or a secrets repository, not both."
            )
        self.token_provider = (
            token_provider
            if token_provider is not None
            else (
                StoredSchwabAccessTokenProvider(secrets_repository)
                if secrets_repository is not None
                else BoundSchwabAccessTokenProvider()
            )
        )
        self.transport = transport or SchwabMarketDataTransport()

    def quotes(
        self,
        symbols: Sequence[str],
        *,
        decision_at: datetime | None = None,
    ) -> dict[str, dict[str, object]]:
        del decision_at
        normalized = normalize_symbols(symbols)
        if not normalized:
            return {}
        access_token = self.token_provider.access_token()
        return {
            symbol: quote.to_shadow_quote()
            for symbol, quote in self.transport.fetch_quotes(
                access_token,
                normalized,
            ).items()
        }

    def quotes_with_clock(
        self,
        symbols: Sequence[str],
        *,
        decision_at: datetime | None = None,
    ) -> SchwabQuoteEvidenceBatch:
        del decision_at
        normalized = normalize_symbols(symbols)
        if not normalized:
            return SchwabQuoteEvidenceBatch({}, {})
        access_token = self.token_provider.access_token()
        batch = self.transport.fetch_quotes_with_clock(
            access_token,
            normalized,
        )
        return SchwabQuoteEvidenceBatch(
            quotes={
                symbol: quote.to_shadow_quote()
                for symbol, quote in batch.quotes.items()
            },
            clock_skew_proof=dict(batch.clock_skew_proof),
        )


def normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        )
    )
    if len(normalized) > MAX_QUOTE_SYMBOLS:
        raise SchwabMarketDataError(
            f"Schwab market data supports at most {MAX_QUOTE_SYMBOLS} symbols per request."
        )
    if any(
        not symbol.replace(".", "").replace("-", "").isalnum()
        for symbol in normalized
    ):
        raise SchwabMarketDataError(
            "Schwab market data received an invalid symbol."
        )
    return normalized


def parse_quote_response(
    payload: object,
    *,
    expected_symbols: Sequence[str],
) -> dict[str, SchwabExecutableQuote]:
    if not isinstance(payload, Mapping):
        raise SchwabMarketDataResponseError(
            "Schwab market data response had an invalid shape."
        )
    parsed: dict[str, SchwabExecutableQuote] = {}
    for symbol in expected_symbols:
        raw_row = payload.get(symbol)
        if raw_row is None:
            continue
        if not isinstance(raw_row, Mapping):
            raise SchwabMarketDataResponseError(
                f"Schwab market data returned an invalid row for {symbol}."
            )
        response_symbol = str(raw_row.get("symbol", "")).strip().upper()
        if response_symbol != symbol:
            raise SchwabMarketDataResponseError(
                f"Schwab market data symbol identity did not match {symbol}."
            )
        raw_quote = raw_row.get("quote")
        if not isinstance(raw_quote, Mapping):
            raise SchwabMarketDataResponseError(
                f"Schwab market data omitted quote evidence for {symbol}."
            )
        parsed[symbol] = parse_quote(symbol, raw_row, raw_quote)
    return parsed


def parse_quote(
    symbol: str,
    row: Mapping[object, object],
    quote: Mapping[object, object],
) -> SchwabExecutableQuote:
    quote_at = epoch_milliseconds(quote.get("quoteTime"), "quoteTime", symbol)
    bid_at = epoch_milliseconds(quote.get("bidTime"), "bidTime", symbol)
    ask_at = epoch_milliseconds(quote.get("askTime"), "askTime", symbol)
    executable_at = min(quote_at, bid_at, ask_at)
    realtime = row.get("realtime") is True
    security_status = str(quote.get("securityStatus", "")).strip()
    trading_state = trading_state_for_status(
        security_status,
        realtime=realtime,
    )
    return SchwabExecutableQuote(
        symbol=symbol,
        timestamp=executable_at.isoformat(),
        provider_quote_timestamp=quote_at.isoformat(),
        provider_bid_timestamp=bid_at.isoformat(),
        provider_ask_timestamp=ask_at.isoformat(),
        bid=optional_float(quote.get("bidPrice")),
        ask=optional_float(quote.get("askPrice")),
        last=optional_float(quote.get("lastPrice")),
        volume=optional_int(quote.get("totalVolume")),
        session=session_for_quote(executable_at),
        trading_state=trading_state,
        realtime=realtime,
        security_status=security_status,
    )


def epoch_milliseconds(
    value: object,
    field_name: str,
    symbol: str,
) -> datetime:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise SchwabMarketDataResponseError(
            f"Schwab market data omitted valid {field_name} for {symbol}."
        )
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise SchwabMarketDataResponseError(
            f"Schwab market data returned invalid {field_name} for {symbol}."
        ) from None


def session_for_quote(observed_at: datetime) -> str:
    eastern = observed_at.astimezone(EASTERN_TZ)
    local_time = eastern.time().replace(tzinfo=None)
    return (
        "regular"
        if time(9, 30) <= local_time < time(16, 0)
        else "extended"
    )


def trading_state_for_status(status: str, *, realtime: bool) -> str:
    if not realtime:
        return "delayed"
    normalized = status.strip().lower()
    if normalized in {"normal", "open", "tradable"}:
        return "tradable"
    if "halt" in normalized:
        return "halted"
    if normalized in {"closed", "closing only"}:
        return "closed"
    return normalized or "unknown"


def optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return int(parsed) if math.isfinite(parsed) else None


def build_regular_market_quote_proof(
    source: object,
    symbols: Sequence[str],
    *,
    checked_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    require_clock_proof: bool = False,
) -> dict[str, object]:
    active_clock = clock or (lambda: datetime.now(timezone.utc))
    requested_at = checked_at or active_clock()
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("Quote proof timestamp must include a UTC offset.")
    normalized = normalize_symbols(symbols)
    if not normalized:
        raise ValueError("Quote proof requires at least one symbol.")
    clock_loader = getattr(source, "quotes_with_clock", None)
    clock_proof: Mapping[str, object] | None = None
    if callable(clock_loader):
        batch = clock_loader(normalized, decision_at=requested_at)
        if not isinstance(batch, SchwabQuoteEvidenceBatch):
            raise SchwabMarketDataResponseError(
                "Schwab market data proof received an invalid clock batch."
            )
        quotes = batch.quotes
        clock_proof = batch.clock_skew_proof
    else:
        loader = getattr(source, "quotes", None)
        if not callable(loader):
            raise TypeError("Quote proof source does not provide batch quotes.")
        quotes = loader(normalized, decision_at=requested_at)
    evaluated_at = checked_at or active_clock()
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError(
            "Quote proof evaluation timestamp must include a UTC offset."
        )
    if evaluated_at < requested_at:
        raise ValueError(
            "Quote proof evaluation timestamp cannot precede the request."
        )
    if not isinstance(quotes, Mapping):
        raise SchwabMarketDataResponseError(
            "Schwab market data proof received an invalid quote collection."
        )

    clock_findings = (
        clock_skew_findings(clock_proof, evaluated_at=evaluated_at)
        if require_clock_proof
        else ()
    )
    trusted_bounds = (
        trusted_clock_bounds(clock_proof, evaluated_at=evaluated_at)
        if require_clock_proof and not clock_findings
        else None
    )
    quote_evaluation_at = (
        trusted_bounds.latest_plausible_trusted_at
        if trusted_bounds is not None
        else evaluated_at
    )
    quote_time_basis = (
        trusted_bounds.to_evidence()
        if trusted_bounds is not None
        else {
            "basis": "LOCAL_EVALUATION_CLOCK",
            "source": "LOCAL_CLOCK",
            "localEvaluatedAt": evaluated_at.isoformat(),
            "estimatedTrustedAt": None,
            "earliestPlausibleTrustedAt": None,
            "latestPlausibleTrustedAt": evaluated_at.isoformat(),
            "signedSkewMilliseconds": None,
            "measurementUncertaintyMilliseconds": None,
        }
    )
    policy = ShadowMarketValidityPolicy()
    results = [
        regular_market_quote_result(
            symbol,
            quotes.get(symbol),
            checked_at=quote_evaluation_at,
            maximum_age_seconds=policy.quote_max_age_seconds,
        )
        for symbol in normalized
    ]
    passed = (
        all(result["status"] == "PASS" for result in results)
        and not clock_findings
    )
    return {
        "schemaVersion": REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION,
        "proofType": "SCHWAB_REGULAR_MARKET_QUOTE_BOUNDARY",
        "proofStatus": "PASS" if passed else "FAIL",
        "evidenceOrigin": UNSPECIFIED_QUOTE_PROOF_ORIGIN,
        "productionSource": False,
        "requestedAt": requested_at.isoformat(),
        "checkedAt": evaluated_at.isoformat(),
        "requestDurationSeconds": round(
            max(0.0, (evaluated_at - requested_at).total_seconds()),
            6,
        ),
        "maximumQuoteAgeSeconds": policy.quote_max_age_seconds,
        "source": SCHWAB_QUOTE_SOURCE,
        "quoteTimeBasis": quote_time_basis,
        "clockSkewProofRequired": require_clock_proof,
        "clockSkewProof": (
            dict(clock_proof)
            if isinstance(clock_proof, Mapping)
            else {
                "status": (
                    "BLOCKED" if require_clock_proof else "NOT_REQUIRED"
                ),
                "findings": list(clock_findings),
            }
        ),
        "clockSkewFindings": list(clock_findings),
        "requestedSymbols": list(normalized),
        "quotes": results,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
    }


def regular_market_quote_result(
    symbol: str,
    raw_quote: object,
    *,
    checked_at: datetime,
    maximum_age_seconds: int,
) -> dict[str, object]:
    findings: list[str] = []
    quote = raw_quote if isinstance(raw_quote, Mapping) else {}
    if not quote:
        findings.append("QUOTE_MISSING")
    if str(quote.get("symbol", "")).strip().upper() != symbol:
        findings.append("SYMBOL_MISMATCH")
    if str(quote.get("source", "")).strip() != SCHWAB_QUOTE_SOURCE:
        findings.append("SOURCE_MISMATCH")
    if quote.get("realtime") is not True:
        findings.append("NOT_REALTIME")
    if str(quote.get("session", "")).strip().lower() != "regular":
        findings.append("SESSION_NOT_REGULAR")
    if str(quote.get("trading_state", "")).strip().lower() not in {
        "open",
        "tradable",
    }:
        findings.append("STATE_NOT_TRADABLE")

    bid = finite_number(quote.get("bid"))
    ask = finite_number(quote.get("ask"))
    if bid is None or ask is None:
        findings.append("BID_ASK_MISSING")
    elif bid <= 0 or ask <= 0 or ask < bid:
        findings.append("BID_ASK_INVALID")

    clock_fields = (
        "timestamp",
        "provider_quote_timestamp",
        "provider_bid_timestamp",
        "provider_ask_timestamp",
    )
    clocks = {
        field_name: parse_offset_datetime(quote.get(field_name))
        for field_name in clock_fields
    }
    for field_name, value in clocks.items():
        if value is None:
            findings.append(f"{field_name.upper()}_INVALID")
        elif field_name != "timestamp" and value > checked_at:
            findings.append(f"{field_name.upper()}_IN_FUTURE")
    quote_at = clocks["timestamp"]
    provider_clocks = [
        clocks["provider_quote_timestamp"],
        clocks["provider_bid_timestamp"],
        clocks["provider_ask_timestamp"],
    ]
    if (
        quote_at is not None
        and all(value is not None for value in provider_clocks)
        and quote_at != min(value for value in provider_clocks if value is not None)
    ):
        findings.append("EXECUTABLE_CLOCK_NOT_OLDEST")

    quote_age_seconds = (
        (checked_at - quote_at).total_seconds()
        if quote_at is not None
        else None
    )
    if quote_age_seconds is not None:
        if quote_age_seconds < 0:
            findings.append("QUOTE_IN_FUTURE")
        elif quote_age_seconds > maximum_age_seconds:
            findings.append("QUOTE_STALE")

    return {
        "symbol": symbol,
        "status": "PASS" if not findings else "FAIL",
        "findings": findings,
        "timestamp": str(quote.get("timestamp", "")),
        "providerQuoteTimestamp": str(
            quote.get("provider_quote_timestamp", "")
        ),
        "providerBidTimestamp": str(
            quote.get("provider_bid_timestamp", "")
        ),
        "providerAskTimestamp": str(
            quote.get("provider_ask_timestamp", "")
        ),
        "quoteAgeSeconds": (
            round(quote_age_seconds, 6)
            if quote_age_seconds is not None
            else None
        ),
        "bid": bid,
        "ask": ask,
        "last": finite_number(quote.get("last")),
        "session": str(quote.get("session", "")),
        "tradingState": str(quote.get("trading_state", "")),
        "realtime": quote.get("realtime") is True,
        "securityStatus": str(quote.get("security_status", "")),
        "source": str(quote.get("source", "")),
    }


def parse_offset_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def write_proof(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(
    argv: list[str] | None = None,
    *,
    source: object | None = None,
    checked_at: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Prove the read-only Schwab regular-market quote boundary."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    proof_parser = subparsers.add_parser(
        "proof",
        help="Fetch and validate provider-timestamped quotes without trading.",
    )
    proof_parser.add_argument("--symbols", nargs="+", required=True)
    proof_parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    assert args.command == "proof"
    production_source = source is None
    active_source = source or SchwabMarketDataQuoteSource()
    evidence_origin = (
        LIVE_SCHWAB_QUOTE_PROOF_ORIGIN
        if production_source
        else INJECTED_QUOTE_PROOF_ORIGIN
    )
    try:
        result = build_regular_market_quote_proof(
            active_source,
            args.symbols,
            checked_at=checked_at,
            require_clock_proof=production_source,
        )
        result["evidenceOrigin"] = evidence_origin
        result["productionSource"] = production_source
    except SchwabMarketDataError as exc:
        now = checked_at or datetime.now(timezone.utc)
        result = {
            "schemaVersion": REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION,
            "proofType": "SCHWAB_REGULAR_MARKET_QUOTE_BOUNDARY",
            "proofStatus": "FAIL",
            "evidenceOrigin": evidence_origin,
            "productionSource": production_source,
            "checkedAt": now.isoformat(),
            "requestedSymbols": list(normalize_symbols(args.symbols)),
            "failure": f"{type(exc).__name__}: {exc}",
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "accountDataIncluded": False,
        }
    if args.output is not None:
        write_proof(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["proofStatus"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
