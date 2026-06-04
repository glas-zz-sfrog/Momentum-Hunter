from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from momentum_hunter.models import Candidate, MarketRegime
from momentum_hunter.news_age import apply_candidate_news_stack
from momentum_hunter.time_utils import now_central


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring_profiles.json"


@dataclass(frozen=True)
class ScoringProfile:
    name: str
    payload: dict


@dataclass(frozen=True)
class RegimeAdjustment:
    price_momentum_multiplier: float = 1.0
    positive_catalyst_multiplier: float = 1.0
    relative_volume_multiplier: float = 1.0
    risk_term_multiplier: float = 1.0


def score_candidate(
    candidate: Candidate,
    regime: MarketRegime = MarketRegime.UNKNOWN,
    profile: ScoringProfile | None = None,
    now: datetime | None = None,
) -> Candidate:
    apply_candidate_news_stack(candidate, now=now)
    profile = profile or load_active_profile()
    adjustment = regime_adjustment(profile, regime)
    score = int(profile.payload.get("base_score", 35))
    reasons: list[str] = []

    market_cap = profile.payload["market_cap"]
    if candidate.market_cap >= market_cap["large_threshold"]:
        score += int(market_cap["large_points"])
        reasons.append("large-cap institutional participation")
    elif candidate.market_cap >= market_cap["mid_threshold"]:
        score += int(market_cap["mid_points"])
        reasons.append("mid/large-cap institutional participation")
    elif candidate.market_cap < market_cap["small_threshold"]:
        score += int(market_cap["small_penalty"])
        reasons.append("market cap below preferred threshold")

    volume = profile.payload["volume"]
    if candidate.volume >= volume["high_threshold"]:
        score += int(volume["high_points"])
        reasons.append(f"{candidate.volume:,} volume")
    elif candidate.volume >= volume["medium_threshold"]:
        score += int(volume["medium_points"])
        reasons.append(f"{candidate.volume:,} volume")

    relative_volume = profile.payload["relative_volume"]
    if candidate.relative_volume >= relative_volume["high_threshold"]:
        score += weighted_points(relative_volume["high_points"], adjustment.relative_volume_multiplier)
        reasons.append(f"{candidate.relative_volume:.1f}x relative volume")
    elif candidate.relative_volume >= relative_volume["medium_threshold"]:
        score += weighted_points(relative_volume["medium_points"], adjustment.relative_volume_multiplier)
        reasons.append(f"{candidate.relative_volume:.1f}x relative volume")

    price_momentum = profile.payload["price_momentum"]
    if candidate.percent_change >= price_momentum["high_threshold"]:
        score += weighted_points(price_momentum["high_points"], adjustment.price_momentum_multiplier)
        reasons.append(f"{candidate.percent_change:.1f}% price momentum")
    elif candidate.percent_change >= price_momentum["medium_threshold"]:
        score += weighted_points(price_momentum["medium_points"], adjustment.price_momentum_multiplier)
        reasons.append(f"{candidate.percent_change:.1f}% price momentum")

    catalyst_text = " ".join([item.headline + " " + item.summary for item in candidate.news]).lower()
    for keyword, points in profile.payload["positive_catalysts"].items():
        if keyword in catalyst_text:
            score += weighted_points(points, adjustment.positive_catalyst_multiplier)
            reasons.append(keyword_to_reason(keyword))

    for keyword, points in profile.payload["risk_terms"].items():
        if keyword in catalyst_text:
            score += weighted_points(points, adjustment.risk_term_multiplier)
            reasons.append(f"risk term: {keyword}")

    low_price = profile.payload["low_price"]
    if candidate.price < low_price["threshold"]:
        score += int(low_price["penalty"])
        reasons.append("price below preferred threshold")

    candidate.score = max(0, min(100, score))
    candidate.score_reasons = dedupe_preserve_order(
        reasons + [f"score profile: {profile.name}", f"score regime: {regime.value}"]
    )
    candidate.score_profile = profile.name
    candidate.score_regime = regime.value
    return candidate


def score_candidates(
    candidates: list[Candidate],
    regime: MarketRegime = MarketRegime.UNKNOWN,
    profile: ScoringProfile | None = None,
    now: datetime | None = None,
) -> list[Candidate]:
    profile = profile or load_active_profile()
    evaluation_time = now or now_central()
    scored = [score_candidate(candidate, regime=regime, profile=profile, now=evaluation_time) for candidate in candidates]
    return sorted(scored, key=lambda item: item.score, reverse=True)


def load_active_profile() -> ScoringProfile:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    name = raw.get("active_profile", "regime-aware-v1")
    return ScoringProfile(name=name, payload=raw["profiles"][name])


def regime_adjustment(profile: ScoringProfile, regime: MarketRegime) -> RegimeAdjustment:
    raw = profile.payload.get("regime_adjustments", {}).get(regime.value, {})
    return RegimeAdjustment(
        price_momentum_multiplier=float(raw.get("price_momentum_multiplier", 1.0)),
        positive_catalyst_multiplier=float(raw.get("positive_catalyst_multiplier", 1.0)),
        relative_volume_multiplier=float(raw.get("relative_volume_multiplier", 1.0)),
        risk_term_multiplier=float(raw.get("risk_term_multiplier", 1.0)),
    )


def weighted_points(points: float, multiplier: float) -> int:
    return int(round(float(points) * multiplier))


def keyword_to_reason(keyword: str) -> str:
    if keyword == "ai":
        return "AI catalyst"
    if keyword == "server":
        return "AI server demand theme"
    if keyword == "price target":
        return "analyst target activity"
    return f"{keyword} catalyst"


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output
