from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.time_utils import now_central


def watchlist_path(for_date: datetime | None = None) -> Path:
    ensure_app_dirs()
    value = for_date or now_central()
    return DATA_DIR / f"watchlist-{value.strftime('%Y-%m-%d')}.json"


def save_watchlist(candidates: list[Candidate], for_date: datetime | None = None) -> Path:
    path = watchlist_path(for_date)
    payload = [candidate_to_dict(candidate) for candidate in candidates]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_watchlist(for_date: datetime | None = None) -> list[Candidate]:
    path = watchlist_path(for_date)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [candidate_from_dict(item) for item in raw]


def candidate_to_dict(candidate: Candidate) -> dict:
    payload = asdict(candidate)
    payload["saved_at"] = candidate.saved_at.isoformat() if candidate.saved_at else None
    payload["news"] = [
        {
            **asdict(item),
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in candidate.news
    ]
    return payload


def candidate_from_dict(payload: dict) -> Candidate:
    news = []
    for item in payload.get("news", []):
        published_at = item.get("published_at")
        news.append(
            NewsItem(
                headline=item.get("headline", ""),
                source=item.get("source", ""),
                published_at=datetime.fromisoformat(published_at) if published_at else None,
                url=item.get("url", ""),
                summary=item.get("summary", ""),
            )
        )
    saved_at = payload.get("saved_at")
    return Candidate(
        ticker=payload.get("ticker", ""),
        company=payload.get("company", ""),
        price=payload.get("price", 0.0),
        percent_change=payload.get("percent_change", 0.0),
        volume=payload.get("volume", 0),
        relative_volume=payload.get("relative_volume", 0.0),
        market_cap=payload.get("market_cap", 0),
        sector=payload.get("sector", ""),
        industry=payload.get("industry", ""),
        float_shares=payload.get("float_shares"),
        short_float=payload.get("short_float"),
        premarket_volume=payload.get("premarket_volume"),
        gap_percent=payload.get("gap_percent"),
        earnings_date=payload.get("earnings_date", ""),
        atr=payload.get("atr"),
        relative_strength=payload.get("relative_strength"),
        news=news,
        score=payload.get("score", 0),
        score_reasons=payload.get("score_reasons", []),
        user_notes=payload.get("user_notes", ""),
        saved_at=datetime.fromisoformat(saved_at) if saved_at else None,
    )
