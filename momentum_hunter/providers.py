from __future__ import annotations

import re
import socket
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Iterable

import requests

from momentum_hunter.models import Candidate, NewsItem, ScannerCriteria
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


FINVIZ_BACKOFF_SECONDS = (10, 30, 60)


class ProviderUnavailableError(RuntimeError):
    def __init__(self, provider: str, message: str, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.provider = provider
        self.reason = reason
        self.user_message = message


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        raise NotImplementedError

    @abstractmethod
    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        raise NotImplementedError


class SampleProvider(MarketDataProvider):
    name = "sample"

    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        current = now_central()
        candidates = [
            Candidate(
                ticker="MU",
                company="Micron Technology",
                price=128.45,
                percent_change=6.8,
                volume=35_200_000,
                relative_volume=2.3,
                market_cap=142_000_000_000,
                sector="Technology",
                industry="Semiconductors",
                news=[
                    NewsItem(
                        headline="Micron rallies after stronger AI memory demand commentary",
                        source="Sample",
                        published_at=current - timedelta(hours=6),
                        summary="AI infrastructure demand and analyst follow-through are supporting momentum.",
                    ),
                    NewsItem(
                        headline="Analysts lift targets following upbeat earnings outlook",
                        source="Sample",
                        published_at=current - timedelta(hours=11),
                        summary="Upgrade and target activity suggests institutional attention.",
                    ),
                ],
            ),
            Candidate(
                ticker="DELL",
                company="Dell Technologies",
                price=151.20,
                percent_change=4.9,
                volume=12_850_000,
                relative_volume=1.7,
                market_cap=105_000_000_000,
                sector="Technology",
                industry="Computer Hardware",
                news=[
                    NewsItem(
                        headline="Dell gains as AI server backlog expands",
                        source="Sample",
                        published_at=current - timedelta(hours=31),
                        summary="AI server demand is the primary catalyst.",
                    )
                ],
            ),
            Candidate(
                ticker="PLTR",
                company="Palantir Technologies",
                price=72.30,
                percent_change=5.4,
                volume=55_000_000,
                relative_volume=1.6,
                market_cap=166_000_000_000,
                sector="Technology",
                industry="Software - Infrastructure",
                news=[
                    NewsItem(
                        headline="Palantir extends move on enterprise AI platform demand",
                        source="Sample",
                        published_at=current - timedelta(days=3),
                        summary="Large-cap momentum and AI theme alignment remain strong.",
                    )
                ],
            ),
            Candidate(
                ticker="XYZP",
                company="Example Microcap",
                price=2.10,
                percent_change=42.0,
                volume=900_000,
                relative_volume=6.8,
                market_cap=85_000_000,
                sector="Healthcare",
                industry="Biotechnology",
                news=[
                    NewsItem(
                        headline="Thinly traded microcap spikes on vague promotion",
                        source="Sample",
                        published_at=current - timedelta(days=28),
                    )
                ],
            ),
        ]
        return filter_candidates(candidates, criteria)

    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        for candidate in self.scan(criteria=_loose_criteria()):
            if candidate.ticker == ticker:
                return candidate.news
        return []


class FinvizProvider(MarketDataProvider):
    name = "finviz"
    base_url = "https://finviz.com"

    def __init__(self, *, sleeper=time.sleep, backoff_seconds: tuple[int, ...] = FINVIZ_BACKOFF_SECONDS) -> None:
        self.sleeper = sleeper
        self.backoff_seconds = backoff_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            }
        )

    def scan(self, criteria: ScannerCriteria) -> list[Candidate]:
        from bs4 import BeautifulSoup

        url = self._screener_url(criteria)
        response = self._get_with_retries(url, action="scan")
        soup = BeautifulSoup(response.text, "lxml")
        table = soup.find("table", class_="screener_table")
        if table is None:
            raise RuntimeError("Finviz screener table was not found. Try Sample provider or update parser.")

        rows = table.find_all("tr")
        candidates: list[Candidate] = []
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) < 11:
                continue
            candidates.append(
                Candidate(
                    ticker=cells[1],
                    company=cells[2],
                    sector=cells[3],
                    industry=cells[4],
                    market_cap=parse_market_cap(cells[6]),
                    price=parse_float(cells[8]),
                    percent_change=parse_percent(cells[9]),
                    volume=parse_int(cells[10]),
                    relative_volume=0.0,
                )
            )

        return filter_candidates(candidates, criteria)

    def fetch_news(self, ticker: str, as_of: datetime | None = None) -> list[NewsItem]:
        from bs4 import BeautifulSoup

        cutoff = as_of or now_central()
        url = f"{self.base_url}/quote.ashx?t={ticker}"
        response = self._get_with_retries(url, action=f"news for {ticker}")
        soup = BeautifulSoup(response.text, "lxml")
        news_table = soup.find(id="news-table")
        if news_table is None:
            return []

        items: list[NewsItem] = []
        for row in news_table.find_all("tr")[:8]:
            link = row.find("a")
            if link is None:
                continue
            timestamp_text = row.find("td").get_text(" ", strip=True) if row.find("td") else ""
            published_at = parse_finviz_news_time(timestamp_text, now=cutoff)
            if published_at is not None and published_at > cutoff:
                continue
            items.append(
                NewsItem(
                    headline=link.get_text(" ", strip=True),
                    source="Finviz",
                    published_at=published_at,
                    url=link.get("href", ""),
                    summary=summarize_catalyst(link.get_text(" ", strip=True)),
                )
            )
        return items

    def _screener_url(self, criteria: ScannerCriteria) -> str:
        cap_filter = "cap_midover" if criteria.min_market_cap >= 2_000_000_000 else "cap_smallover"
        price_filter = "sh_price_o10" if criteria.min_price >= 10 else "sh_price_o5"
        volume_filter = "sh_avgvol_o3000" if criteria.min_volume >= 3_000_000 else "sh_avgvol_o1000"
        change_filter = "ta_change_u3" if criteria.min_percent_change <= 3 else "ta_change_u5"
        filters = ",".join([cap_filter, price_filter, volume_filter, change_filter])
        return f"{self.base_url}/screener.ashx?v=111&f={filters}&o=-volume"

    def _get_with_retries(self, url: str, *, action: str) -> requests.Response:
        last_error: Exception | None = None
        attempts = len(self.backoff_seconds) + 1
        for attempt in range(attempts):
            try:
                response = self.session.get(url, timeout=20)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < len(self.backoff_seconds):
                    self.sleeper(self.backoff_seconds[attempt])
                    continue
                raise provider_error_from_exception(self.name, action, exc) from exc
        raise provider_error_from_exception(self.name, action, last_error or RuntimeError("unknown provider failure"))


def provider_from_name(name: str) -> MarketDataProvider:
    if name == FinvizProvider.name:
        return FinvizProvider()
    return SampleProvider()


def provider_error_from_exception(provider: str, action: str, exc: BaseException) -> ProviderUnavailableError:
    if is_dns_failure(exc):
        return ProviderUnavailableError(
            provider=provider,
            reason="dns_failure",
            message=f"Provider unavailable / DNS failure while running {provider} {action}.",
        )
    return ProviderUnavailableError(
        provider=provider,
        reason="request_failure",
        message=f"Provider unavailable while running {provider} {action}.",
    )


def is_dns_failure(exc: BaseException | None) -> bool:
    current = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        message = str(current).lower()
        if "getaddrinfo failed" in message or "failed to resolve" in message or "name resolution" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def parse_finviz_news_time(value: str, now: datetime | None = None) -> datetime | None:
    value = " ".join(value.split())
    if not value:
        return None
    current = now or now_central()
    parts = value.split()
    try:
        if len(parts) == 1:
            parsed_time = datetime.strptime(parts[0], "%I:%M%p").time()
            return datetime.combine(current.date(), parsed_time, tzinfo=CENTRAL_TZ)
        date_text, time_text = parts[0], parts[1]
        parsed_time = datetime.strptime(time_text, "%I:%M%p").time()
        if date_text.lower() == "today":
            return datetime.combine(current.date(), parsed_time, tzinfo=CENTRAL_TZ)
        if date_text.lower() == "yesterday":
            return datetime.combine((current - timedelta(days=1)).date(), parsed_time, tzinfo=CENTRAL_TZ)
        parsed_date = datetime.strptime(date_text, "%b-%d-%y").date()
        return datetime.combine(parsed_date, parsed_time, tzinfo=CENTRAL_TZ)
    except ValueError:
        return None


def filter_candidates(candidates: Iterable[Candidate], criteria: ScannerCriteria) -> list[Candidate]:
    filtered = [
        candidate
        for candidate in candidates
        if candidate.volume >= criteria.min_volume
        and candidate.percent_change >= criteria.min_percent_change
        and candidate.market_cap >= criteria.min_market_cap
        and candidate.price >= criteria.min_price
        and (candidate.relative_volume == 0.0 or candidate.relative_volume >= criteria.min_relative_volume)
    ]
    return sorted(filtered, key=lambda item: (item.score, item.volume, item.percent_change), reverse=True)


def summarize_catalyst(headline: str) -> str:
    headline_lower = headline.lower()
    catalyst_map = {
        "earnings": "Potential earnings catalyst.",
        "guidance": "Potential guidance catalyst.",
        "upgrade": "Potential analyst upgrade catalyst.",
        "price target": "Potential analyst target catalyst.",
        "ai": "Potential AI infrastructure or automation theme.",
        "partnership": "Potential partnership catalyst.",
        "fda": "Potential FDA catalyst.",
    }
    for keyword, summary in catalyst_map.items():
        if keyword in headline_lower:
            return summary
    return "Review headline for catalyst quality."


def parse_market_cap(value: str) -> int:
    match = re.match(r"([\d.]+)([MBT])", value.replace(",", "").upper())
    if not match:
        return 0
    number = float(match.group(1))
    multiplier = {"M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[match.group(2)]
    return int(number * multiplier)


def parse_percent(value: str) -> float:
    return parse_float(value.replace("%", ""))


def parse_float(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0


def parse_int(value: str) -> int:
    try:
        return int(float(value.replace(",", "")))
    except ValueError:
        return 0


def _loose_criteria() -> ScannerCriteria:
    return ScannerCriteria("Loose", 0, 0, 0, 0, 0)
