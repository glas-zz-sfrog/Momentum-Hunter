from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from momentum_hunter.models import Candidate, MarketRegime
from momentum_hunter.news_age import apply_candidate_news_stack, filter_news_known_at_capture
from momentum_hunter.time_utils import now_central


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring_profiles.json"
SCORE_ENGINE_VERSION = "momentum_score_v1"
SCORE_EXPLANATION_SCHEMA_VERSION = "score-breakdown-v1"


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
    breakdown = build_score_breakdown(candidate, regime=regime, profile=profile, now=now)
    candidate.score = int(breakdown["computed_final_score"])
    candidate.score_reasons = breakdown["score_reasons"]
    candidate.score_profile = breakdown["score_profile"]
    candidate.score_regime = breakdown["score_regime"]
    return candidate


def build_score_breakdown(
    candidate: Candidate,
    regime: MarketRegime = MarketRegime.UNKNOWN,
    profile: ScoringProfile | None = None,
    now: datetime | None = None,
    *,
    identity: dict | None = None,
    stored_final_score: int | None = None,
    generated_at: datetime | None = None,
) -> dict:
    evaluation_time = now or now_central()
    generated_at = generated_at or now_central()
    apply_candidate_news_stack(candidate, now=evaluation_time)
    profile = profile or load_active_profile()
    adjustment = regime_adjustment(profile, regime)
    components: list[dict] = []
    reasons: list[str] = []

    base_score = int(profile.payload.get("base_score", 35))
    add_component(
        components,
        key="base_score",
        label="Base Score",
        raw_inputs={"base_score": base_score},
        rule="Profile base_score starts every candidate.",
        before=base_score,
        after=base_score,
        explanation=f"Every candidate starts at {base_score} before momentum and risk rules.",
        category="base",
    )

    market_cap = profile.payload["market_cap"]
    market_cap_points = 0
    market_cap_reason = ""
    market_cap_rule = (
        f">= {market_cap['large_threshold']:,} => +{market_cap['large_points']}; "
        f">= {market_cap['mid_threshold']:,} => +{market_cap['mid_points']}; "
        f"< {market_cap['small_threshold']:,} => {market_cap['small_penalty']}"
    )
    if candidate.market_cap >= market_cap["large_threshold"]:
        market_cap_points = int(market_cap["large_points"])
        market_cap_reason = "large-cap institutional participation"
    elif candidate.market_cap >= market_cap["mid_threshold"]:
        market_cap_points = int(market_cap["mid_points"])
        market_cap_reason = "mid/large-cap institutional participation"
    elif candidate.market_cap < market_cap["small_threshold"]:
        market_cap_points = int(market_cap["small_penalty"])
        market_cap_reason = "market cap below preferred threshold"
    add_component(
        components,
        key="market_cap",
        label="Market Cap",
        raw_inputs={"market_cap": candidate.market_cap},
        rule=market_cap_rule,
        before=market_cap_points,
        after=market_cap_points,
        explanation=market_cap_reason or "Market cap did not cross a scoring threshold.",
        reason=market_cap_reason,
    )
    if market_cap_reason:
        reasons.append(market_cap_reason)

    volume = profile.payload["volume"]
    volume_points = 0
    volume_reason = ""
    if candidate.volume >= volume["high_threshold"]:
        volume_points = int(volume["high_points"])
        volume_reason = f"{candidate.volume:,} volume"
    elif candidate.volume >= volume["medium_threshold"]:
        volume_points = int(volume["medium_points"])
        volume_reason = f"{candidate.volume:,} volume"
    add_component(
        components,
        key="volume",
        label="Volume",
        raw_inputs={"volume": candidate.volume},
        rule=(
            f">= {volume['high_threshold']:,} => +{volume['high_points']}; "
            f">= {volume['medium_threshold']:,} => +{volume['medium_points']}"
        ),
        before=volume_points,
        after=volume_points,
        explanation=volume_reason or "Volume did not cross a scoring threshold.",
        reason=volume_reason,
    )
    if volume_reason:
        reasons.append(volume_reason)

    relative_volume = profile.payload["relative_volume"]
    relative_volume_base_points = 0
    relative_volume_points = 0
    relative_volume_reason = ""
    if candidate.relative_volume >= relative_volume["high_threshold"]:
        relative_volume_base_points = int(relative_volume["high_points"])
        relative_volume_points = weighted_points(relative_volume["high_points"], adjustment.relative_volume_multiplier)
        relative_volume_reason = f"{candidate.relative_volume:.1f}x relative volume"
    elif candidate.relative_volume >= relative_volume["medium_threshold"]:
        relative_volume_base_points = int(relative_volume["medium_points"])
        relative_volume_points = weighted_points(relative_volume["medium_points"], adjustment.relative_volume_multiplier)
        relative_volume_reason = f"{candidate.relative_volume:.1f}x relative volume"
    add_component(
        components,
        key="relative_volume",
        label="Relative Volume",
        raw_inputs={"relative_volume": candidate.relative_volume, "multiplier": adjustment.relative_volume_multiplier},
        rule=(
            f">= {relative_volume['high_threshold']}x => +{relative_volume['high_points']}; "
            f">= {relative_volume['medium_threshold']}x => +{relative_volume['medium_points']}; "
            "then apply regime relative-volume multiplier"
        ),
        before=relative_volume_base_points,
        after=relative_volume_points,
        explanation=relative_volume_reason or "Relative volume did not cross a scoring threshold.",
        reason=relative_volume_reason,
    )
    if relative_volume_reason:
        reasons.append(relative_volume_reason)

    price_momentum = profile.payload["price_momentum"]
    price_momentum_base_points = 0
    price_momentum_points = 0
    price_momentum_reason = ""
    if candidate.percent_change >= price_momentum["high_threshold"]:
        price_momentum_base_points = int(price_momentum["high_points"])
        price_momentum_points = weighted_points(price_momentum["high_points"], adjustment.price_momentum_multiplier)
        price_momentum_reason = f"{candidate.percent_change:.1f}% price momentum"
    elif candidate.percent_change >= price_momentum["medium_threshold"]:
        price_momentum_base_points = int(price_momentum["medium_points"])
        price_momentum_points = weighted_points(price_momentum["medium_points"], adjustment.price_momentum_multiplier)
        price_momentum_reason = f"{candidate.percent_change:.1f}% price momentum"
    add_component(
        components,
        key="price_momentum",
        label="Price Momentum",
        raw_inputs={"percent_change": candidate.percent_change, "multiplier": adjustment.price_momentum_multiplier},
        rule=(
            f">= {price_momentum['high_threshold']}% => +{price_momentum['high_points']}; "
            f">= {price_momentum['medium_threshold']}% => +{price_momentum['medium_points']}; "
            "then apply regime price-momentum multiplier"
        ),
        before=price_momentum_base_points,
        after=price_momentum_points,
        explanation=price_momentum_reason or "Price change did not cross a scoring threshold.",
        reason=price_momentum_reason,
    )
    if price_momentum_reason:
        reasons.append(price_momentum_reason)

    scoring_news = filter_news_known_at_capture(candidate.news, evaluation_time)
    catalyst_text = " ".join([item.headline + " " + item.summary for item in scoring_news]).lower()
    matched_positive_catalyst = False
    for keyword, points in profile.payload["positive_catalysts"].items():
        if keyword in catalyst_text:
            matched_positive_catalyst = True
            adjusted = weighted_points(points, adjustment.positive_catalyst_multiplier)
            reason = keyword_to_reason(keyword)
            add_component(
                components,
                key=f"positive_catalyst.{keyword}",
                label=f"Positive Catalyst: {keyword}",
                raw_inputs={
                    "keyword": keyword,
                    "headline_count_known_at_score_time": len(scoring_news),
                    "base_points": points,
                    "multiplier": adjustment.positive_catalyst_multiplier,
                },
                rule="Keyword must appear in news known at the scoring timestamp; then apply regime catalyst multiplier.",
                before=int(points),
                after=adjusted,
                explanation=reason,
                reason=reason,
                category="bonus",
            )
            reasons.append(reason)
    if not matched_positive_catalyst:
        add_component(
            components,
            key="positive_catalysts.none",
            label="Positive Catalysts",
            raw_inputs={"headline_count_known_at_score_time": len(scoring_news)},
            rule="Configured positive catalyst keywords must appear in known news.",
            before=0,
            after=0,
            explanation="No configured positive catalyst keyword was found in news known at the scoring timestamp.",
        )

    matched_risk_term = False
    for keyword, points in profile.payload["risk_terms"].items():
        if keyword in catalyst_text:
            matched_risk_term = True
            adjusted = weighted_points(points, adjustment.risk_term_multiplier)
            reason = f"risk term: {keyword}"
            add_component(
                components,
                key=f"risk_term.{keyword}",
                label=f"Risk Term: {keyword}",
                raw_inputs={
                    "keyword": keyword,
                    "headline_count_known_at_score_time": len(scoring_news),
                    "base_points": points,
                    "multiplier": adjustment.risk_term_multiplier,
                },
                rule="Keyword must appear in news known at the scoring timestamp; then apply regime risk multiplier.",
                before=int(points),
                after=adjusted,
                explanation=reason,
                reason=reason,
                category="penalty",
            )
            reasons.append(reason)
    if not matched_risk_term:
        add_component(
            components,
            key="risk_terms.none",
            label="Risk Terms",
            raw_inputs={"headline_count_known_at_score_time": len(scoring_news)},
            rule="Configured risk keywords subtract points when present in known news.",
            before=0,
            after=0,
            explanation="No configured risk keyword was found in news known at the scoring timestamp.",
        )

    low_price = profile.payload["low_price"]
    low_price_points = 0
    low_price_reason = ""
    if candidate.price < low_price["threshold"]:
        low_price_points = int(low_price["penalty"])
        low_price_reason = "price below preferred threshold"
    add_component(
        components,
        key="low_price",
        label="Low Price Risk",
        raw_inputs={"price": candidate.price},
        rule=f"< ${low_price['threshold']:.2f} => {low_price['penalty']}",
        before=low_price_points,
        after=low_price_points,
        explanation=low_price_reason or "Price is not below the low-price risk threshold.",
        reason=low_price_reason,
        category="penalty" if low_price_points < 0 else "component",
    )
    if low_price_reason:
        reasons.append(low_price_reason)

    pre_floor_total = sum(int(component["points_after_adjustment"]) for component in components)
    floor_output = max(0, pre_floor_total)
    final_score = min(100, floor_output)
    final_score = int(final_score)
    score_reasons = dedupe_preserve_order(
        reasons + [f"score profile: {profile.name}", f"score regime: {regime.value}"]
    )
    computed_status = "complete"
    reconciliation_status = "OK"
    displayed_final_score = final_score if stored_final_score is None else int(stored_final_score)
    if stored_final_score is not None and int(stored_final_score) != final_score:
        computed_status = "legacy"
        reconciliation_status = "LEGACY_SCORE_MISMATCH"

    breakdown = {
        "schema_version": 1,
        "explanation_schema_version": SCORE_EXPLANATION_SCHEMA_VERSION,
        "score_engine_version": SCORE_ENGINE_VERSION,
        "score_profile": profile.name,
        "score_regime": regime.value,
        "status": computed_status,
        "generated_at": generated_at.isoformat(),
        "evaluation_time": evaluation_time.isoformat(),
        "identity": identity or {},
        "ticker": candidate.ticker,
        "company": candidate.company,
        "final_score": displayed_final_score,
        "computed_final_score": final_score,
        "stored_final_score": stored_final_score,
        "subtotal_before_global_adjustments": pre_floor_total,
        "pre_floor_total": pre_floor_total,
        "pre_cap_total": floor_output,
        "components": components,
        "bonuses": [component["key"] for component in components if int(component["points_after_adjustment"]) > 0 and component["key"] != "base_score"],
        "penalties": [component["key"] for component in components if int(component["points_after_adjustment"]) < 0],
        "caps": [
            {
                "key": "global_cap",
                "label": "Global Cap",
                "limit": 100,
                "applied": floor_output > 100,
                "input": floor_output,
                "output": final_score,
                "explanation": "Scores are capped at 100 after all components and floor handling.",
            }
        ],
        "floors": [
            {
                "key": "global_floor",
                "label": "Global Floor",
                "limit": 0,
                "applied": pre_floor_total < 0,
                "input": pre_floor_total,
                "output": floor_output,
                "explanation": "Scores are floored at 0 before the global cap is applied.",
            }
        ],
        "overrides": [],
        "score_reasons": score_reasons,
        "reconciliation": {
            "component_total": pre_floor_total,
            "floor_output": floor_output,
            "cap_output": final_score,
            "displayed_final_score": displayed_final_score,
            "status": reconciliation_status,
        },
        "reconciliation_status": reconciliation_status,
    }
    return breakdown


def add_component(
    components: list[dict],
    *,
    key: str,
    label: str,
    raw_inputs: dict,
    rule: str,
    before: int,
    after: int,
    explanation: str,
    reason: str = "",
    category: str | None = None,
) -> None:
    points_after = int(after)
    component_category = category or ("bonus" if points_after > 0 else "penalty" if points_after < 0 else "component")
    components.append(
        {
            "key": key,
            "label": label,
            "raw_inputs": raw_inputs,
            "rule": rule,
            "points_before_adjustment": int(before),
            "points_after_adjustment": points_after,
            "explanation": explanation,
            "reason": reason,
            "category": component_category,
        }
    )


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


def load_profile(name: str | None = None) -> ScoringProfile:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    profile_name = name or raw.get("active_profile", "regime-aware-v1")
    if profile_name not in raw["profiles"]:
        profile_name = raw.get("active_profile", "regime-aware-v1")
    return ScoringProfile(name=profile_name, payload=raw["profiles"][profile_name])


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
