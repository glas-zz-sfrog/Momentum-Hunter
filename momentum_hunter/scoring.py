from __future__ import annotations

from momentum_hunter.models import Candidate


POSITIVE_CATALYSTS = {
    "earnings": 12,
    "beat": 10,
    "guidance": 10,
    "raise": 8,
    "upgrade": 10,
    "price target": 7,
    "ai": 10,
    "server": 6,
    "partnership": 6,
    "fda": 6,
}


RISK_TERMS = {
    "offering": -12,
    "dilution": -10,
    "investigation": -10,
    "bankruptcy": -20,
    "promotion": -8,
}


def score_candidate(candidate: Candidate) -> Candidate:
    score = 35
    reasons: list[str] = []

    if candidate.market_cap >= 50_000_000_000:
        score += 12
        reasons.append("large-cap institutional participation")
    elif candidate.market_cap >= 5_000_000_000:
        score += 9
        reasons.append("mid/large-cap institutional participation")
    elif candidate.market_cap < 1_000_000_000:
        score -= 25
        reasons.append("market cap below preferred threshold")

    if candidate.volume >= 25_000_000:
        score += 12
        reasons.append(f"{candidate.volume:,} volume")
    elif candidate.volume >= 3_000_000:
        score += 8
        reasons.append(f"{candidate.volume:,} volume")

    if candidate.relative_volume >= 2.0:
        score += 10
        reasons.append(f"{candidate.relative_volume:.1f}x relative volume")
    elif candidate.relative_volume >= 1.2:
        score += 6
        reasons.append(f"{candidate.relative_volume:.1f}x relative volume")

    if candidate.percent_change >= 8:
        score += 8
        reasons.append(f"{candidate.percent_change:.1f}% price momentum")
    elif candidate.percent_change >= 3:
        score += 5
        reasons.append(f"{candidate.percent_change:.1f}% price momentum")

    catalyst_text = " ".join([item.headline + " " + item.summary for item in candidate.news]).lower()
    for keyword, points in POSITIVE_CATALYSTS.items():
        if keyword in catalyst_text:
            score += points
            reasons.append(keyword_to_reason(keyword))

    for keyword, points in RISK_TERMS.items():
        if keyword in catalyst_text:
            score += points
            reasons.append(f"risk term: {keyword}")

    if candidate.price < 5:
        score -= 20
        reasons.append("price below preferred threshold")

    candidate.score = max(0, min(100, score))
    candidate.score_reasons = dedupe_preserve_order(reasons)
    return candidate


def score_candidates(candidates: list[Candidate]) -> list[Candidate]:
    scored = [score_candidate(candidate) for candidate in candidates]
    return sorted(scored, key=lambda item: item.score, reverse=True)


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
