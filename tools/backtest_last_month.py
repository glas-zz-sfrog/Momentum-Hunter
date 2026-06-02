from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from momentum_hunter.models import BASE_MOMENTUM, INSTITUTIONAL_MOMENTUM, ScannerCriteria


@dataclass
class DailyBar:
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int


def main() -> None:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        }
    )

    symbols = fetch_sp500_symbols(session)
    since = datetime.now().date() - timedelta(days=120)
    test_start = datetime.now().date() - timedelta(days=35)

    all_bars: dict[str, list[DailyBar]] = {}
    for index, symbol in enumerate(symbols, 1):
        bars = fetch_yahoo_bars(session, symbol, since)
        if len(bars) >= 25:
            all_bars[symbol] = bars
        if index % 75 == 0:
            print(f"Fetched {index}/{len(symbols)} symbols...")
        time.sleep(0.03)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe": "Current S&P 500 constituents from Wikipedia",
        "symbols_loaded": len(all_bars),
        "methodology": (
            "Daily close-to-close signal using percent change, volume, price, and "
            "relative volume. Relative volume is volume divided by prior 20-trading-day "
            "average volume. Forward returns are measured from signal close to next "
            "trading-day close and fifth trading-day close. Market-cap filters are "
            "treated as satisfied for the S&P 500 universe."
        ),
        "presets": {
            BASE_MOMENTUM.name: evaluate(all_bars, BASE_MOMENTUM, test_start),
            INSTITUTIONAL_MOMENTUM.name: evaluate(all_bars, INSTITUTIONAL_MOMENTUM, test_start),
        },
    }

    print(json.dumps(report, indent=2))


def fetch_sp500_symbols(session: requests.Session) -> list[str]:
    response = session.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    table = soup.find("table", id="constituents")
    if table is None:
        raise RuntimeError("Could not find S&P 500 constituents table.")
    symbols = []
    for row in table.select("tbody tr")[1:]:
        cells = row.select("td")
        if cells:
            symbols.append(cells[0].get_text(strip=True).replace(".", "-"))
    return symbols


def fetch_yahoo_bars(session: requests.Session, symbol: str, since: date) -> list[DailyBar]:
    period1 = int(datetime.combine(since, datetime.min.time()).timestamp())
    period2 = int(datetime.now().timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )
    response = session.get(url, timeout=20)
    if response.status_code != 200:
        return []
    payload = response.json()
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return []
    timestamps = result[0].get("timestamp") or []
    quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result[0].get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    bars = []
    for index, timestamp in enumerate(timestamps):
        try:
            open_price = quote["open"][index]
            high = quote["high"][index]
            low = quote["low"][index]
            close = quote["close"][index]
            adjusted_close = adjclose[index] if index < len(adjclose) else close
            volume = quote["volume"][index]
        except (KeyError, IndexError):
            continue
        if None in (open_price, high, low, close, adjusted_close, volume):
            continue
        bars.append(
            DailyBar(
                symbol=symbol,
                day=datetime.fromtimestamp(timestamp).date(),
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(adjusted_close),
                volume=int(volume),
            )
        )
    return bars


def evaluate(all_bars: dict[str, list[DailyBar]], criteria: ScannerCriteria, test_start: date) -> dict:
    signals = []
    for symbol, bars in all_bars.items():
        for index in range(21, len(bars) - 5):
            previous = bars[index - 1]
            current = bars[index]
            if current.day < test_start:
                continue
            percent_change = ((current.close - previous.close) / previous.close) * 100
            avg_volume = statistics.mean(bar.volume for bar in bars[index - 20 : index])
            relative_volume = current.volume / avg_volume if avg_volume else 0
            if (
                current.volume >= criteria.min_volume
                and percent_change >= criteria.min_percent_change
                and current.close >= criteria.min_price
                and relative_volume >= criteria.min_relative_volume
            ):
                next_close = bars[index + 1].close
                fifth_close = bars[index + 5].close
                signals.append(
                    {
                        "symbol": symbol,
                        "date": current.day.isoformat(),
                        "close": round(current.close, 2),
                        "change_pct": round(percent_change, 2),
                        "volume": current.volume,
                        "rel_volume": round(relative_volume, 2),
                        "next_day_return_pct": round(((next_close - current.close) / current.close) * 100, 2),
                        "five_day_return_pct": round(((fifth_close - current.close) / current.close) * 100, 2),
                    }
                )

    next_returns = [item["next_day_return_pct"] for item in signals]
    five_returns = [item["five_day_return_pct"] for item in signals]
    return {
        "signal_count": len(signals),
        "next_day_avg_pct": round(statistics.mean(next_returns), 2) if next_returns else None,
        "next_day_median_pct": round(statistics.median(next_returns), 2) if next_returns else None,
        "next_day_win_rate_pct": round(win_rate(next_returns), 1) if next_returns else None,
        "five_day_avg_pct": round(statistics.mean(five_returns), 2) if five_returns else None,
        "five_day_median_pct": round(statistics.median(five_returns), 2) if five_returns else None,
        "five_day_win_rate_pct": round(win_rate(five_returns), 1) if five_returns else None,
        "best_five": sorted(signals, key=lambda item: item["five_day_return_pct"], reverse=True)[:5],
        "worst_five": sorted(signals, key=lambda item: item["five_day_return_pct"])[:5],
    }


def win_rate(values: list[float]) -> float:
    return (sum(1 for value in values if value > 0) / len(values)) * 100


if __name__ == "__main__":
    main()
