from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable

from momentum_hunter.models import Candidate, NewsItem


DIRECT_ISSUER = "DIRECT_ISSUER"
SECTOR = "SECTOR"
PEER = "PEER"
CUSTOMER_SUPPLIER = "CUSTOMER_SUPPLIER"
MACRO = "MACRO"
UNRESOLVED = "UNRESOLVED"

RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_ELIGIBLE = "EXECUTION_ELIGIBLE"
EXECUTION_INELIGIBLE = "EXECUTION_INELIGIBLE"

CATALYST_SCORE_SUPPORTED = "SUPPORTED"
CATALYST_SCORE_BLOCKED = "BLOCKED"

_COMPANY_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "group",
    "holdings",
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "plc",
}
_AMBIGUOUS_TICKERS = {
    "A",
    "AI",
    "ALL",
    "ARE",
    "FOR",
    "IT",
    "ON",
    "SO",
}
_TICKER_STOP_WORDS = _AMBIGUOUS_TICKERS | {
    "CEO",
    "CFO",
    "EPS",
    "ETF",
    "FED",
    "GDP",
    "IPO",
    "SEC",
    "USA",
}
_MACRO_TERMS = (
    "federal reserve",
    "fed rate",
    "fomc",
    "inflation",
    "interest rate",
    "jobs report",
    "nonfarm payroll",
    "tariff",
    "treasury yield",
)


@dataclass(frozen=True)
class PriceFieldEvidence:
    label: str
    source: str
    provider_timestamp: str | None
    local_receipt_timestamp: str | None
    age_seconds: float | None
    authentication_status: str
    result_status: str
    authority: str = RESEARCH_ONLY


@dataclass(frozen=True)
class CatalystAttribution:
    source_article: str
    source_publisher: str
    source_url: str
    source_published_at: str | None
    mentioned_ticker: str | None
    mentioned_company: str | None
    candidate_ticker: str
    candidate_company: str
    relationship_type: str
    relationship_evidence: str
    score_authority: str


def make_price_evidence(
    *,
    label: str,
    source: str,
    provider_timestamp: str | None = None,
    local_receipt_timestamp: str | None = None,
    authentication_status: str = "NOT_APPLICABLE",
    result_status: str = "AVAILABLE",
    authority: str = RESEARCH_ONLY,
) -> PriceFieldEvidence:
    return PriceFieldEvidence(
        label=label,
        source=source,
        provider_timestamp=provider_timestamp,
        local_receipt_timestamp=local_receipt_timestamp,
        age_seconds=None,
        authentication_status=authentication_status,
        result_status=result_status,
        authority=authority,
    )


def evidence_with_age(
    evidence: PriceFieldEvidence,
    *,
    as_of: datetime,
) -> PriceFieldEvidence:
    timestamp = parse_evidence_timestamp(
        evidence.provider_timestamp or evidence.local_receipt_timestamp
    )
    age_seconds = None
    if timestamp is not None and timestamp.tzinfo is not None and as_of.tzinfo is not None:
        age_seconds = round(max(0.0, (as_of - timestamp).total_seconds()), 3)
    return replace(evidence, age_seconds=age_seconds)


def unavailable_price_evidence(
    *,
    label: str,
    source: str,
    result_status: str = "UNAVAILABLE",
) -> PriceFieldEvidence:
    return make_price_evidence(
        label=label,
        source=source,
        result_status=result_status,
    )


def classify_catalyst_attribution(
    candidate: Candidate,
    headline: str,
) -> CatalystAttribution:
    item = catalyst_news_item(candidate.news, headline)
    mentioned_ticker = extract_mentioned_ticker(headline)
    candidate_symbol_mentioned = ticker_is_explicit(candidate.ticker, headline)
    company_mentioned = company_is_explicit(candidate.company, headline)
    normalized_company = normalized_company_name(candidate.company)

    if candidate_symbol_mentioned or company_mentioned:
        relationship_type = DIRECT_ISSUER
        score_authority = CATALYST_SCORE_SUPPORTED
        evidence = (
            f"Headline explicitly names candidate ticker {candidate.ticker.upper()}."
            if candidate_symbol_mentioned
            else f"Headline explicitly names candidate company {normalized_company}."
        )
        if mentioned_ticker is None and candidate_symbol_mentioned:
            mentioned_ticker = candidate.ticker.upper()
        mentioned_company = candidate.company or None
    elif is_macro_headline(headline):
        relationship_type = MACRO
        score_authority = CATALYST_SCORE_SUPPORTED
        evidence = "Headline contains an explicit broad-market or macroeconomic term."
        mentioned_company = None
    else:
        relationship_type = UNRESOLVED
        score_authority = CATALYST_SCORE_BLOCKED
        evidence = (
            "Stored article metadata does not prove a direct issuer, sector, peer, "
            "customer/supplier, or macro relationship to the candidate."
        )
        mentioned_company = None

    return CatalystAttribution(
        source_article=headline,
        source_publisher=item.source if item is not None else "",
        source_url=item.url if item is not None else "",
        source_published_at=(
            item.published_at.isoformat()
            if item is not None and item.published_at is not None
            else None
        ),
        mentioned_ticker=mentioned_ticker,
        mentioned_company=mentioned_company,
        candidate_ticker=candidate.ticker.upper(),
        candidate_company=candidate.company,
        relationship_type=relationship_type,
        relationship_evidence=evidence,
        score_authority=score_authority,
    )


def catalyst_news_item(
    items: Iterable[NewsItem],
    headline: str,
) -> NewsItem | None:
    normalized = normalize_text(headline)
    for item in items:
        if normalize_text(item.headline or item.summary) == normalized:
            return item
    return None


def ticker_is_explicit(ticker: str, headline: str) -> bool:
    symbol = ticker.strip().upper()
    if not symbol or symbol in _AMBIGUOUS_TICKERS:
        return False
    return bool(
        re.search(
            rf"(?<![A-Z0-9])(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)?{re.escape(symbol)}(?![A-Z0-9])",
            headline.upper(),
        )
    )


def extract_mentioned_ticker(headline: str) -> str | None:
    patterns = (
        r"\$([A-Z][A-Z0-9.\-]{0,5})\b",
        r"\b(?:NASDAQ|NYSE)\s*:\s*([A-Z][A-Z0-9.\-]{0,5})\b",
        r"\b([A-Z][A-Z0-9.\-]{1,5})\s+(?:[Ss]tock|[Ss]hares)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, headline)
        if match and match.group(1).upper() not in _TICKER_STOP_WORDS:
            return match.group(1).upper()
    return None


def company_is_explicit(company: str, headline: str) -> bool:
    normalized_company = normalized_company_name(company)
    if len(normalized_company) < 3:
        return False
    return normalized_company in normalize_text(headline)


def normalized_company_name(company: str) -> str:
    words = normalize_text(company).split()
    while words and words[-1] in _COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def is_macro_headline(headline: str) -> bool:
    normalized = normalize_text(headline)
    return any(term in normalized for term in _MACRO_TERMS)


def normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def parse_evidence_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
