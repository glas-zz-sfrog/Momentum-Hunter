from __future__ import annotations

"""Read-only Schwab candle acquisition with an explicitly inactive staging boundary."""

import argparse
import json
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import requests

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_market_data import (
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataAuthorizationError,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof


SCHWAB_PRICE_HISTORY_URL = "https://api.schwabapi.com/marketdata/v1/pricehistory"
SCHWAB_PRICE_HISTORY_SOURCE = "schwab_marketdata_v1_pricehistory"
SCHWAB_PRICE_HISTORY_CLOCK_SOURCE = "schwab_marketdata_v1_pricehistory:https_date"
STAGED_CANDLE_SCHEMA_VERSION = 1
DEFAULT_STAGING_PATH = DATA_DIR / "staging" / "schwab-candle-preview.json"
OPPORTUNITY_MINUTE_BARS_PATH = DATA_DIR / "opportunity-minute-bars.json"
DAILY_OHLC_SOURCE_PATH = DATA_DIR / "daily-ohlc-bars.json"
ACTIVE_CANDLE_PATHS = frozenset(
    {
        OPPORTUNITY_MINUTE_BARS_PATH,
        DAILY_OHLC_SOURCE_PATH,
    }
)
HTTP_TIMEOUT = (5.0, 30.0)
MAX_PRICE_HISTORY_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PRICE_HISTORY_SYMBOLS = 25
SUPPORTED_PRICE_HISTORY_INTERVALS = frozenset({"1m", "Daily"})
INTRADAY_LOOKBACK = timedelta(days=7)
MAX_PROVIDER_FUTURE = timedelta(seconds=5)


class SchwabPriceHistoryError(RuntimeError):
    pass


class SchwabPriceHistoryAuthorizationError(SchwabPriceHistoryError):
    pass


class SchwabPriceHistoryNetworkError(SchwabPriceHistoryError):
    pass


class SchwabPriceHistoryResponseError(SchwabPriceHistoryError):
    pass


class SchwabPriceHistoryStagingError(SchwabPriceHistoryError):
    pass


@dataclass(frozen=True)
class SchwabPriceBar:
    symbol: str
    interval: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str = SCHWAB_PRICE_HISTORY_SOURCE


@dataclass(frozen=True)
class SchwabPriceHistoryResult:
    symbol: str
    interval: str
    requested_at: str
    received_at: str
    previous_close: float | None
    previous_close_date: str
    bars: tuple[SchwabPriceBar, ...]
    clock_skew_proof: dict[str, object]
    source: str = SCHWAB_PRICE_HISTORY_SOURCE


class SchwabPriceHistoryTransport:
    """Exact-host GET-only transport for Schwab historical OHLCV."""

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

    def fetch(
        self,
        access_token: str,
        symbol: str,
        interval: str,
    ) -> SchwabPriceHistoryResult:
        if not str(access_token).strip():
            raise SchwabPriceHistoryAuthorizationError(
                "Schwab price history requires an active OAuth access token."
            )
        clean_symbol = normalize_symbol(symbol)
        clean_interval = normalize_interval(interval)
        requested_at = require_aware(self.clock(), "Price-history request start")
        try:
            response = self.session.get(
                SCHWAB_PRICE_HISTORY_URL,
                params=price_history_parameters(
                    clean_symbol,
                    clean_interval,
                    observed_at=requested_at,
                ),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabPriceHistoryNetworkError(
                "Schwab price history could not reach the exact configured endpoint."
            ) from None
        received_at = require_aware(self.clock(), "Price-history response time")
        if response.is_redirect:
            raise SchwabPriceHistoryResponseError(
                "Schwab price history refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise SchwabPriceHistoryResponseError(
                f"Schwab price history failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_PRICE_HISTORY_RESPONSE_BYTES:
            raise SchwabPriceHistoryResponseError(
                "Schwab price history response exceeded the size limit."
            )
        try:
            payload = response.json()
        except ValueError:
            raise SchwabPriceHistoryResponseError(
                "Schwab price history response was not valid JSON."
            ) from None
        headers = getattr(response, "headers", {})
        remote_date_header = (
            str(headers.get("Date", ""))
            if isinstance(headers, Mapping)
            else ""
        )
        return parse_price_history_response(
            payload,
            expected_symbol=clean_symbol,
            interval=clean_interval,
            requested_at=requested_at,
            received_at=received_at,
            remote_date_header=remote_date_header,
        )


class SchwabPriceHistorySource:
    """Bound-token source with no account, order, or active-chart write capability."""

    def __init__(
        self,
        *,
        token_provider: object | None = None,
        transport: SchwabPriceHistoryTransport | None = None,
    ) -> None:
        self.token_provider = token_provider or BoundSchwabAccessTokenProvider()
        self.transport = transport or SchwabPriceHistoryTransport()

    def history(
        self,
        symbol: str,
        interval: str,
    ) -> SchwabPriceHistoryResult:
        clean_symbol = normalize_symbol(symbol)
        clean_interval = normalize_interval(interval)
        return self.transport.fetch(
            self._access_token(),
            clean_symbol,
            clean_interval,
        )

    def _access_token(self) -> str:
        try:
            return self.token_provider.access_token()
        except SchwabMarketDataAuthorizationError as exc:
            raise SchwabPriceHistoryAuthorizationError(
                "Schwab price history OAuth refresh or binding validation failed safely."
            ) from exc

    def history_batch(
        self,
        symbols: Sequence[str],
        intervals: Sequence[str],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        normalized_symbols = normalize_symbols(symbols)
        normalized_intervals = tuple(
            dict.fromkeys(normalize_interval(item) for item in intervals)
        )
        if not normalized_intervals:
            raise ValueError("At least one price-history interval is required.")
        access_token = self._access_token()
        return tuple(
            self.transport.fetch(access_token, symbol, interval)
            for symbol in normalized_symbols
            for interval in normalized_intervals
        )


def price_history_parameters(
    symbol: str,
    interval: str,
    *,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    clean_symbol = normalize_symbol(symbol)
    clean_interval = normalize_interval(interval)
    if clean_interval == "1m":
        observed_at = require_aware(
            observed_at or datetime.now(timezone.utc),
            "Price-history parameter time",
        )
        return {
            "symbol": clean_symbol,
            "frequencyType": "minute",
            "frequency": 1,
            "startDate": epoch_milliseconds(observed_at - INTRADAY_LOOKBACK),
            "endDate": epoch_milliseconds(observed_at),
            "needExtendedHoursData": "false",
            "needPreviousClose": "true",
        }
    return {
        "symbol": clean_symbol,
        "periodType": "year",
        "period": 1,
        "frequencyType": "daily",
        "frequency": 1,
        "needExtendedHoursData": "false",
        "needPreviousClose": "true",
    }


def parse_price_history_response(
    payload: object,
    *,
    expected_symbol: str,
    interval: str,
    requested_at: datetime,
    received_at: datetime,
    remote_date_header: str,
) -> SchwabPriceHistoryResult:
    clean_symbol = normalize_symbol(expected_symbol)
    clean_interval = normalize_interval(interval)
    requested_at = require_aware(requested_at, "Price-history request start")
    received_at = require_aware(received_at, "Price-history response time")
    if received_at < requested_at:
        raise SchwabPriceHistoryResponseError(
            "Schwab price history response time preceded request time."
        )
    if not isinstance(payload, Mapping):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history response had an invalid shape."
        )
    response_symbol = str(payload.get("symbol", "")).strip().upper()
    if response_symbol != clean_symbol:
        raise SchwabPriceHistoryResponseError(
            "Schwab price history symbol identity did not match the request."
        )
    raw_candles = payload.get("candles")
    if not isinstance(raw_candles, list):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history response omitted the candle collection."
        )
    bars = tuple(
        sorted(
            (
                parse_price_bar(
                    item,
                    symbol=clean_symbol,
                    interval=clean_interval,
                )
                for item in raw_candles
            ),
            key=lambda item: item.timestamp,
        )
    )
    timestamps = [item.timestamp for item in bars]
    if len(timestamps) != len(set(timestamps)):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history response contained duplicate candle timestamps."
        )
    if payload.get("empty") is False and not bars:
        raise SchwabPriceHistoryResponseError(
            "Schwab price history reported a nonempty response without candles."
        )
    if bars:
        latest = parse_timestamp(bars[-1].timestamp)
        if latest > received_at + MAX_PROVIDER_FUTURE:
            raise SchwabPriceHistoryResponseError(
                "Schwab price history returned a future-dated candle."
            )
    clock_skew_proof = build_https_clock_skew_proof(
        request_started_at=requested_at,
        response_received_at=received_at,
        remote_date_header=remote_date_header,
        source_identity=SCHWAB_PRICE_HISTORY_CLOCK_SOURCE,
    )
    if clock_skew_proof.get("status") != "PASS":
        raise SchwabPriceHistoryResponseError(
            "Schwab price history HTTPS clock proof did not pass."
        )
    return SchwabPriceHistoryResult(
        symbol=clean_symbol,
        interval=clean_interval,
        requested_at=timestamp_text(requested_at),
        received_at=timestamp_text(received_at),
        previous_close=optional_finite_float(payload.get("previousClose")),
        previous_close_date=epoch_milliseconds_text(
            payload.get("previousCloseDate"),
            required=False,
        ),
        bars=bars,
        clock_skew_proof=clock_skew_proof,
    )


def parse_price_bar(
    payload: object,
    *,
    symbol: str,
    interval: str,
) -> SchwabPriceBar:
    if not isinstance(payload, Mapping):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history contained an invalid candle."
        )
    open_value = required_price(payload.get("open"), "open")
    high = required_price(payload.get("high"), "high")
    low = required_price(payload.get("low"), "low")
    close = required_price(payload.get("close"), "close")
    if high < max(open_value, low, close):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history candle contained an impossible high."
        )
    if low > min(open_value, high, close):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history candle contained an impossible low."
        )
    volume = required_volume(payload.get("volume"))
    return SchwabPriceBar(
        symbol=symbol,
        interval=interval,
        timestamp=epoch_milliseconds_text(payload.get("datetime"), required=True),
        open=open_value,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def write_staged_price_history(
    results: Sequence[SchwabPriceHistoryResult],
    *,
    path: Path = DEFAULT_STAGING_PATH,
    active_paths: Sequence[Path] = tuple(ACTIVE_CANDLE_PATHS),
) -> Path:
    target = Path(path).resolve()
    protected = {Path(item).resolve() for item in active_paths}
    if target in protected:
        raise SchwabPriceHistoryStagingError(
            "Schwab candle staging cannot overwrite an active chart source."
        )
    normalized = tuple(results)
    if not normalized:
        raise SchwabPriceHistoryStagingError(
            "Schwab candle staging requires at least one price-history result."
        )
    keys = [(item.symbol, item.interval) for item in normalized]
    if len(keys) != len(set(keys)):
        raise SchwabPriceHistoryStagingError(
            "Schwab candle staging received a duplicate symbol/interval result."
        )
    payload = {
        "schemaVersion": STAGED_CANDLE_SCHEMA_VERSION,
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "generatedAt": timestamp_text(datetime.now(timezone.utc)),
        "readOnlyProvider": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
        "results": [
            {
                "symbol": item.symbol,
                "interval": item.interval,
                "requestedAt": item.requested_at,
                "receivedAt": item.received_at,
                "previousClose": item.previous_close,
                "previousCloseDate": item.previous_close_date,
                "clockSkewProof": item.clock_skew_proof,
                "bars": [asdict(bar) for bar in item.bars],
            }
            for item in sorted(
                normalized,
                key=lambda item: (item.symbol, item.interval),
            )
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def normalize_symbol(symbol: object) -> str:
    normalized = str(symbol).strip().upper()
    if (
        not normalized
        or len(normalized) > 12
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
            for character in normalized
        )
    ):
        raise ValueError("Price-history symbol must contain 1-12 ticker characters.")
    return normalized


def normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            normalize_symbol(item)
            for item in symbols
            if str(item).strip()
        )
    )
    if not normalized:
        raise ValueError("At least one price-history symbol is required.")
    if len(normalized) > MAX_PRICE_HISTORY_SYMBOLS:
        raise ValueError(
            f"Price-history requests support at most {MAX_PRICE_HISTORY_SYMBOLS} symbols."
        )
    return normalized


def normalize_interval(interval: object) -> str:
    normalized = str(interval).strip()
    if normalized not in SUPPORTED_PRICE_HISTORY_INTERVALS:
        raise ValueError(
            f"Unsupported price-history interval: {normalized or '<empty>'}."
        )
    return normalized


def required_price(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabPriceHistoryResponseError(
            f"Schwab price history candle omitted a valid {field_name}."
        )
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise SchwabPriceHistoryResponseError(
            f"Schwab price history candle omitted a valid {field_name}."
        )
    return parsed


def required_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history candle omitted valid volume."
        )
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or not parsed.is_integer():
        raise SchwabPriceHistoryResponseError(
            "Schwab price history candle omitted valid volume."
        )
    return int(parsed)


def optional_finite_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history returned an invalid previous close."
        )
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise SchwabPriceHistoryResponseError(
            "Schwab price history returned an invalid previous close."
        )
    return parsed


def epoch_milliseconds_text(value: object, *, required: bool) -> str:
    if value is None and not required:
        return ""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history returned an invalid epoch timestamp."
        )
    try:
        parsed = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise SchwabPriceHistoryResponseError(
            "Schwab price history returned an invalid epoch timestamp."
        ) from None
    return timestamp_text(parsed)


def epoch_milliseconds(value: datetime) -> int:
    return int(require_aware(value, "Price-history epoch time").timestamp() * 1000)


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise SchwabPriceHistoryResponseError(
            "Schwab price history returned an invalid timestamp."
        ) from None
    return require_aware(parsed, "Price-history timestamp")


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabPriceHistoryResponseError(
            f"{field_name} must include a UTC offset."
        )
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return require_aware(value, "Price-history timestamp").isoformat().replace(
        "+00:00",
        "Z",
    )


def result_summary(
    results: Sequence[SchwabPriceHistoryResult],
    *,
    staged_path: Path | None,
) -> dict[str, object]:
    return {
        "schemaVersion": STAGED_CANDLE_SCHEMA_VERSION,
        "status": "PASS",
        "mode": "SCHWAB_PRICE_HISTORY_READ_ONLY_PREVIEW",
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
        "stagedPath": str(staged_path) if staged_path is not None else "",
        "results": [
            {
                "symbol": item.symbol,
                "interval": item.interval,
                "barCount": len(item.bars),
                "firstBar": item.bars[0].timestamp if item.bars else "",
                "lastBar": item.bars[-1].timestamp if item.bars else "",
                "clockStatus": item.clock_skew_proof.get("status", ""),
            }
            for item in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview read-only Schwab candles without activating chart data."
    )
    parser.add_argument("command", choices=("preview",))
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument(
        "--intervals",
        nargs="+",
        default=["1m", "Daily"],
        choices=sorted(SUPPORTED_PRICE_HISTORY_INTERVALS),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        results = SchwabPriceHistorySource().history_batch(
            args.symbols,
            args.intervals,
        )
        staged_path = (
            write_staged_price_history(results, path=args.output)
            if args.output is not None
            else None
        )
        summary = result_summary(results, staged_path=staged_path)
    except (SchwabPriceHistoryError, ValueError) as exc:
        summary = {
            "schemaVersion": STAGED_CANDLE_SCHEMA_VERSION,
            "mode": "SCHWAB_PRICE_HISTORY_READ_ONLY_PREVIEW",
            "status": "FAILED_SAFE",
            "failure": f"{type(exc).__name__}: {exc}",
            "activeChartSource": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "accountDataIncluded": False,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
