from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from momentum_hunter.models import MarketRegime


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    regime: MarketRegime
    symbol: str
    close: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    reason: str = ""


def detect_market_regime(symbol: str = "SPY") -> MarketRegimeSnapshot:
    try:
        closes = fetch_daily_closes(symbol)
    except Exception as exc:
        return MarketRegimeSnapshot(
            regime=MarketRegime.UNKNOWN,
            symbol=symbol,
            reason=f"Market regime unavailable: {exc}",
        )

    if len(closes) < 200:
        return MarketRegimeSnapshot(
            regime=MarketRegime.UNKNOWN,
            symbol=symbol,
            reason="Market regime unavailable: fewer than 200 daily closes.",
        )

    close = closes[-1]
    sma_50 = sum(closes[-50:]) / 50
    sma_200 = sum(closes[-200:]) / 200
    if close > sma_50 and sma_50 > sma_200:
        regime = MarketRegime.BULL
        reason = "SPY is above its 50-day average, and the 50-day average is above the 200-day average."
    elif close < sma_50 and sma_50 < sma_200:
        regime = MarketRegime.BEAR
        reason = "SPY is below its 50-day average, and the 50-day average is below the 200-day average."
    else:
        regime = MarketRegime.NEUTRAL
        reason = "SPY trend is mixed against the 50-day and 200-day averages."

    return MarketRegimeSnapshot(
        regime=regime,
        symbol=symbol,
        close=close,
        sma_50=sma_50,
        sma_200=sma_200,
        reason=reason,
    )


def fetch_daily_closes(symbol: str) -> list[float]:
    period1 = int((datetime.now() - timedelta(days=420)).timestamp())
    period2 = int(datetime.now().timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        }
    )
    response = session.get(url, timeout=15)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("chart", {}).get("result") or []
    if not result:
        raise RuntimeError("Yahoo chart response did not include results.")
    adjclose = (result[0].get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    raw_close = quote.get("close") or []
    closes = [value for value in (adjclose or raw_close) if value is not None]
    return [float(value) for value in closes]
