from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class CaptureSession(str, Enum):
    MORNING = "morning"
    EVENING = "evening"
    MANUAL = "manual"


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScannerCriteria:
    name: str
    min_volume: int
    min_percent_change: float
    min_market_cap: int
    min_price: float
    min_relative_volume: float


@dataclass
class NewsItem:
    headline: str
    source: str = ""
    published_at: datetime | None = None
    url: str = ""
    summary: str = ""


@dataclass
class NewsStack:
    article_count: int = 0
    valid_timestamp_count: int = 0
    known_timestamp_count: int = 0
    unknown_timestamp_count: int = 0
    future_timestamp_count: int = 0
    excluded_from_scoring_count: int = 0
    latest_article_age_hours: float | None = None
    oldest_article_age_hours: float | None = None
    latest_article_published_at: datetime | None = None
    oldest_article_published_at: datetime | None = None
    freshest_headline: str = ""
    freshest_url: str = ""
    freshness: str = "UNKNOWN"
    freshness_score: int = 0


@dataclass
class Candidate:
    ticker: str
    company: str = ""
    price: float = 0.0
    percent_change: float = 0.0
    volume: int = 0
    relative_volume: float = 0.0
    market_cap: int = 0
    sector: str = ""
    industry: str = ""
    float_shares: int | None = None
    short_float: float | None = None
    premarket_volume: int | None = None
    gap_percent: float | None = None
    earnings_date: str = ""
    atr: float | None = None
    relative_strength: float | None = None
    news: list[NewsItem] = field(default_factory=list)
    score: int = 0
    news_stack: NewsStack = field(default_factory=NewsStack)
    news_hours_old: float | None = None
    freshness: str = "UNKNOWN"
    freshness_score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    score_profile: str = ""
    score_regime: str = ""
    user_notes: str = ""
    saved_at: datetime | None = None


BASE_MOMENTUM = ScannerCriteria(
    name="Base Momentum",
    min_volume=1_000_000,
    min_percent_change=5.0,
    min_market_cap=1_000_000_000,
    min_price=5.0,
    min_relative_volume=1.50,
)

INSTITUTIONAL_MOMENTUM = ScannerCriteria(
    name="Institutional Momentum",
    min_volume=3_000_000,
    min_percent_change=3.0,
    min_market_cap=5_000_000_000,
    min_price=10.0,
    min_relative_volume=1.20,
)

SCANNER_PRESETS = {
    BASE_MOMENTUM.name: BASE_MOMENTUM,
    INSTITUTIONAL_MOMENTUM.name: INSTITUTIONAL_MOMENTUM,
}
