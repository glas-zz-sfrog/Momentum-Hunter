from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.historical_clusters import (
    SCANNER_ALL,
    SECTOR_ALL,
    classify_candidate_cluster,
    common_component_labels,
    load_outcome_rows,
    parse_int,
    scanner_name,
)
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.replay import outcome_key
from momentum_hunter.review import CandidateIdentity, load_review_decisions, make_capture_id
from momentum_hunter.scheduling import classify_capture
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH, find_score_breakdown, score_breakdown_identity
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.study import REGIME_ALL, REVIEW_ALL, SESSION_ALL, StudyFilter, parse_optional_float


CATALYST_RESEARCH_LABEL = "CATALYST CLUSTERS — RESEARCH ONLY"
HISTORICAL_THEME_ALL = "all historical themes"
SAMPLE_SIZE_WARNING_LIMIT = 10


@dataclass(frozen=True)
class CatalystHeadline:
    cluster_name: str
    headline: str
    ticker: str
    capture_time: str
    capture_date: str
    session: str
    provider: str
    scanner: str
    sector: str
    industry: str
    market_regime: str
    source: str
    url: str
    published_at: str
    timestamp_status: str
    headline_age_hours: float | None
    freshness_label: str
    score: int
    review_status: str
    outcome_status: str
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    next_day_return_pct: float | None
    five_day_return_pct: float | None
    historical_theme: str
    score_components: list[str] = field(default_factory=list)
    is_study_eligible: bool = False


@dataclass(frozen=True)
class CatalystClusterSummary:
    name: str
    headline_count: int
    candidate_count: int
    unique_ticker_count: int
    tickers: list[str]
    date_range: str
    average_score: float | None
    average_max_gain_pct: float | None
    average_max_drawdown_pct: float | None
    win_rate_pct: float | None
    representative_headlines: list[str]
    top_winners: list[str]
    worst_failures: list[str]
    warnings: list[str] = field(default_factory=list)
    headlines: list[CatalystHeadline] = field(default_factory=list)


@dataclass(frozen=True)
class CatalystClusterReport:
    label: str
    source: str
    total_headlines: int
    total_candidates: int
    excluded_future_headlines: int
    filters: StudyFilter
    clusters: list[CatalystClusterSummary]
    warnings: list[str] = field(default_factory=list)


def build_catalyst_cluster_report(
    *,
    study_filter: StudyFilter | None = None,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
) -> CatalystClusterReport:
    study_filter = study_filter or StudyFilter()
    headlines, excluded_future_count = load_catalyst_headlines(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    filtered = filter_catalyst_headlines(headlines, study_filter)
    grouped: dict[str, list[CatalystHeadline]] = defaultdict(list)
    for headline in filtered:
        grouped[headline.cluster_name].append(headline)

    clusters = [
        summarize_catalyst_cluster(name, rows)
        for name, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    warnings = []
    if excluded_future_count:
        warnings.append(f"Excluded {excluded_future_count} future-timestamp headline(s) from catalyst clustering.")
    if not headlines:
        warnings.append("No stored historical headlines found in active raw captures.")
    if not filtered and headlines:
        warnings.append("Filters removed all stored historical headlines.")
    return CatalystClusterReport(
        label=CATALYST_RESEARCH_LABEL,
        source="active raw captures + score-breakdowns.json + review-decisions.json + analysis-outcomes.csv",
        total_headlines=len(filtered),
        total_candidates=len({candidate_key(headline) for headline in filtered}),
        excluded_future_headlines=excluded_future_count,
        filters=study_filter,
        clusters=clusters,
        warnings=warnings,
    )


def load_catalyst_headlines(
    *,
    captures_dir: Path,
    score_breakdowns_path: Path,
    review_decisions_path: Path,
    outcomes_csv: Path,
) -> tuple[list[CatalystHeadline], int]:
    review_decisions = load_review_decisions(review_decisions_path)
    outcomes = load_outcome_rows(outcomes_csv)
    rows: list[CatalystHeadline] = []
    future_count = 0
    for capture_path in sorted(captures_dir.rglob("*.json")):
        payload = load_json(capture_path)
        if not payload:
            continue
        capture_time = payload.get("capture_time", "")
        capture_dt = parse_datetime(capture_time)
        capture_date = payload.get("capture_date", capture_time[:10])
        session = payload.get("session", "")
        provider = payload.get("provider", "")
        scanner = scanner_name(payload)
        mode = payload.get("mode", "")
        market_regime = (payload.get("market", {}).get("regime") or payload.get("scoring", {}).get("regime") or "unknown").lower()
        classification = classify_capture(capture_time, session, capture_date=capture_date)
        sector_counts = Counter(str(item.get("sector", "") or "unknown") for item in payload.get("candidates", []))
        for candidate_payload in payload.get("candidates", []):
            ticker = str(candidate_payload.get("ticker", "")).upper()
            sector = str(candidate_payload.get("sector", "") or "unknown")
            identity = CandidateIdentity(
                capture_id=make_capture_id(capture_date, session, provider, scanner),
                capture_date=capture_date,
                session=session,
                provider=provider,
                scanner=scanner,
                ticker=ticker,
            )
            review = review_decisions.get(identity.key)
            outcome = outcomes.get(outcome_key(capture_date, capture_time, session, provider, scanner, ticker), {})
            score_identity = score_breakdown_identity(
                capture_date=capture_date,
                capture_time=capture_time,
                session=session,
                provider=provider,
                scanner=scanner,
                ticker=ticker,
                mode=mode,
            )
            breakdown = find_score_breakdown(score_identity, path=score_breakdowns_path)
            candidate_theme = classify_candidate_theme(
                candidate_payload,
                capture_date=capture_date,
                capture_time=capture_time,
                session=session,
                provider=provider,
                scanner=scanner,
                market_regime=market_regime,
                review_status=review.review_status.value if review else "unreviewed",
                outcome=outcome,
                score_components=common_component_labels(breakdown),
                is_study_eligible=classification.is_study_eligible,
                sector_sympathy=sector_counts.get(sector, 0) >= 2,
            )
            candidate_news = candidate_payload.get("news", [])
            news_items = candidate_news if isinstance(candidate_news, list) and candidate_news else [synthetic_no_headline()]
            for news_item in news_items:
                if not isinstance(news_item, dict):
                    continue
                headline = str(news_item.get("headline", "")).strip()
                if not headline:
                    headline = "No stored headline"
                timestamp_status, age_hours = timestamp_status_and_age(news_item.get("published_at", ""), capture_dt)
                if timestamp_status == "future":
                    future_count += 1
                    continue
                rows.append(
                    CatalystHeadline(
                        cluster_name=classify_catalyst_headline(headline, sector=sector, industry=str(candidate_payload.get("industry", "")), sector_sympathy=sector_counts.get(sector, 0) >= 2),
                        headline=headline,
                        ticker=ticker,
                        capture_time=capture_time,
                        capture_date=capture_date,
                        session=session,
                        provider=provider,
                        scanner=scanner,
                        sector=sector,
                        industry=str(candidate_payload.get("industry", "") or "unknown"),
                        market_regime=market_regime,
                        source=str(news_item.get("source", "")),
                        url=str(news_item.get("url", "")),
                        published_at=str(news_item.get("published_at", "")),
                        timestamp_status=timestamp_status,
                        headline_age_hours=age_hours,
                        freshness_label=freshness_label(age_hours, timestamp_status),
                        score=parse_int(candidate_payload.get("score")),
                        review_status=review.review_status.value if review else "unreviewed",
                        outcome_status=outcome.get("outcome_status", "missing") if outcome else "missing",
                        max_gain_pct=parse_optional_float(outcome.get("max_gain_pct", "")),
                        max_drawdown_pct=parse_optional_float(outcome.get("max_drawdown_pct", "")),
                        next_day_return_pct=parse_optional_float(outcome.get("next_day_return_pct", "")),
                        five_day_return_pct=parse_optional_float(outcome.get("five_day_return_pct", "")),
                        historical_theme=candidate_theme,
                        score_components=common_component_labels(breakdown),
                        is_study_eligible=classification.is_study_eligible,
                    )
                )
    return rows, future_count


def filter_catalyst_headlines(headlines: list[CatalystHeadline], study_filter: StudyFilter) -> list[CatalystHeadline]:
    filtered = headlines
    if not study_filter.include_non_study_eligible:
        filtered = [headline for headline in filtered if headline.is_study_eligible]
    if study_filter.start_date:
        filtered = [headline for headline in filtered if headline.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [headline for headline in filtered if headline.capture_date <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [headline for headline in filtered if headline.session == study_filter.session]
    if study_filter.regime != REGIME_ALL:
        filtered = [headline for headline in filtered if headline.market_regime == study_filter.regime]
    if study_filter.scanner != SCANNER_ALL:
        filtered = [headline for headline in filtered if headline.scanner == study_filter.scanner]
    if study_filter.sector != SECTOR_ALL:
        filtered = [headline for headline in filtered if headline.sector == study_filter.sector]
    if study_filter.minimum_score:
        filtered = [headline for headline in filtered if headline.score >= study_filter.minimum_score]
    if study_filter.review_status != REVIEW_ALL:
        filtered = [headline for headline in filtered if headline.review_status == study_filter.review_status]
    if study_filter.historical_cluster_theme != HISTORICAL_THEME_ALL:
        filtered = [headline for headline in filtered if headline.historical_theme == study_filter.historical_cluster_theme]
    return filtered


def summarize_catalyst_cluster(name: str, rows: list[CatalystHeadline]) -> CatalystClusterSummary:
    dates = sorted({row.capture_date for row in rows if row.capture_date})
    candidate_keys = {candidate_key(row) for row in rows}
    max_gains_by_candidate = first_metric_by_candidate(rows, "max_gain_pct")
    drawdowns_by_candidate = first_metric_by_candidate(rows, "max_drawdown_pct")
    win_values = [
        value
        for value in first_metric_by_candidate(rows, "five_day_return_pct", fallback="next_day_return_pct").values()
        if value is not None
    ]
    missing_outcomes = sum(1 for key in candidate_keys if max_gains_by_candidate.get(key) is None)
    warnings = []
    if len(candidate_keys) < SAMPLE_SIZE_WARNING_LIMIT:
        warnings.append(f"Sample size {len(candidate_keys)} - diagnostic only.")
    if missing_outcomes:
        warnings.append(f"Missing outcome data for {missing_outcomes} candidate(s); metrics use available rows only.")
    unknown_timestamps = sum(1 for row in rows if row.timestamp_status == "unknown")
    if unknown_timestamps:
        warnings.append(f"Timestamp unknown for {unknown_timestamps} headline(s); freshness not inferred.")
    return CatalystClusterSummary(
        name=name,
        headline_count=len(rows),
        candidate_count=len(candidate_keys),
        unique_ticker_count=len({row.ticker for row in rows}),
        tickers=sorted({row.ticker for row in rows}),
        date_range=f"{dates[0]} to {dates[-1]}" if dates else "unknown",
        average_score=average(list(first_metric_by_candidate(rows, "score").values())),
        average_max_gain_pct=average([value for value in max_gains_by_candidate.values() if value is not None]),
        average_max_drawdown_pct=average([value for value in drawdowns_by_candidate.values() if value is not None]),
        win_rate_pct=win_rate(win_values),
        representative_headlines=representative_headlines(rows),
        top_winners=ranked_tickers(rows, "gain"),
        worst_failures=ranked_tickers(rows, "drawdown"),
        warnings=warnings,
        headlines=sorted(rows, key=lambda row: (row.capture_time, row.ticker, row.headline)),
    )


def classify_candidate_theme(
    candidate_payload: dict,
    *,
    capture_date: str,
    capture_time: str,
    session: str,
    provider: str,
    scanner: str,
    market_regime: str,
    review_status: str,
    outcome: dict,
    score_components: list[str],
    is_study_eligible: bool,
    sector_sympathy: bool,
) -> str:
    from momentum_hunter.historical_clusters import ClusterCandidate

    headlines = [
        str(item.get("headline", ""))
        for item in candidate_payload.get("news", [])
        if isinstance(item, dict)
    ]
    return classify_candidate_cluster(
        ClusterCandidate(
            capture_date=capture_date,
            capture_time=capture_time,
            session=session,
            provider=provider,
            scanner=scanner,
            ticker=str(candidate_payload.get("ticker", "")).upper(),
            sector=str(candidate_payload.get("sector", "") or "unknown"),
            industry=str(candidate_payload.get("industry", "") or "unknown"),
            market_regime=market_regime,
            score=parse_int(candidate_payload.get("score")),
            review_status=review_status,
            headlines=headlines,
            catalyst_keywords=catalyst_keywords_for_headline(" ".join(headlines), sector_sympathy=sector_sympathy),
            score_components=score_components,
            max_gain_pct=parse_optional_float(outcome.get("max_gain_pct", "")),
            max_drawdown_pct=parse_optional_float(outcome.get("max_drawdown_pct", "")),
            next_day_return_pct=parse_optional_float(outcome.get("next_day_return_pct", "")),
            five_day_return_pct=parse_optional_float(outcome.get("five_day_return_pct", "")),
            outcome_status=outcome.get("outcome_status", "missing") if outcome else "missing",
            is_study_eligible=is_study_eligible,
        )
    )


def classify_catalyst_headline(headline: str, *, sector: str, industry: str, sector_sympathy: bool) -> str:
    lowered = headline.lower()
    if any(term in lowered for term in ["beats", "beat estimates", "tops estimates", "eps beat", "earnings beat", "record revenue"]):
        return "Earnings beat"
    if any(term in lowered for term in ["raises guidance", "raised guidance", "guidance raise", "raises outlook", "boosts outlook"]):
        return "Guidance raise"
    if any(term in lowered for term in ["earnings", "eps", "quarterly results", "guidance", "outlook"]):
        return "Earnings/guidance general"
    if any(term in lowered for term in ["upgrade", "upgraded", "initiated at buy", "initiates buy"]):
        return "Analyst upgrade"
    if any(term in lowered for term in ["price target", "target raise", "raised target", "target lifted"]):
        return "Analyst target raise"
    if any(term in lowered for term in ["downgrade", "downgraded", "cut to sell", "lowered rating"]):
        return "Analyst downgrade"
    if any(term in lowered for term in ["ai partnership", "artificial intelligence partnership"]):
        return "AI partnership"
    if any(term in f" {lowered} " for term in [" ai ", "artificial intelligence", "data center", "datacenter", "server", "gpu", "semiconductor"]):
        return "AI infrastructure"
    if any(term in lowered for term in ["contract", "customer win", "award", "partnership", "deal with", "selected by"]):
        return "Contract / customer win"
    if any(term in lowered for term in ["fda approval", "fda approves", "approved by fda", "clearance"]):
        return "FDA approval"
    if any(term in lowered for term in ["fda", "pdufa", "complete response", "resubmission"]):
        return "FDA binary event"
    if any(term in lowered for term in ["phase 3", "phase iii", "clinical", "trial data", "study results"]):
        return "Biotech clinical data"
    if any(term in lowered for term in ["acquisition", "acquires", "merger", "buyout", "takeover"]):
        return "Merger / acquisition"
    if any(term in lowered for term in ["fed", "inflation", "tariff", "jobs report", "cpi", "macro"]):
        return "Macro-only"
    if any(term in lowered for term in ["rumor", "speculation", "meme", "reddit", "short squeeze", "hype"]):
        return "Weak / vague catalyst"
    if sector_sympathy:
        return "Sector sympathy"
    if not headline or headline == "No stored headline":
        return "No clear catalyst"
    return "Unknown / uncategorized"


def catalyst_keywords_for_headline(text: str, *, sector_sympathy: bool) -> list[str]:
    cluster = classify_catalyst_headline(text, sector="", industry="", sector_sympathy=sector_sympathy)
    compatibility = {
        "Earnings beat": ["earnings", "beat"],
        "Guidance raise": ["guidance"],
        "Earnings/guidance general": ["earnings"],
        "Analyst upgrade": ["upgrade", "analyst"],
        "Analyst target raise": ["price target", "analyst"],
        "Analyst downgrade": ["downgrade", "analyst"],
        "AI infrastructure": ["ai"],
        "AI partnership": ["ai"],
        "FDA approval": ["fda", "approval"],
        "FDA binary event": ["fda"],
        "Biotech clinical data": ["trial"],
        "Weak / vague catalyst": ["speculation"],
        "Sector sympathy": ["sector sympathy"],
    }
    return compatibility.get(cluster, [])


def timestamp_status_and_age(published_at: object, capture_dt: datetime | None) -> tuple[str, float | None]:
    if not published_at:
        return "unknown", None
    published_dt = parse_datetime(str(published_at))
    if published_dt is None or capture_dt is None:
        return "unknown", None
    if published_dt > capture_dt:
        return "future", None
    age_hours = round((capture_dt - published_dt).total_seconds() / 3600, 4)
    return "known", max(0.0, age_hours)


def freshness_label(age_hours: float | None, timestamp_status: str) -> str:
    if timestamp_status == "future":
        return "FUTURE_TIMESTAMP"
    if timestamp_status == "unknown" or age_hours is None:
        return "UNKNOWN_TIMESTAMP"
    if age_hours < 24:
        return "HOT"
    if age_hours <= 72:
        return "ACTIVE"
    return "STALE"


def representative_headlines(rows: list[CatalystHeadline], limit: int = 3) -> list[str]:
    counts = Counter(row.headline for row in rows)
    return [
        headline
        for headline, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def ranked_tickers(rows: list[CatalystHeadline], metric: str) -> list[str]:
    metric_name = "max_gain_pct" if metric == "gain" else "max_drawdown_pct"
    values = first_metric_by_candidate(rows, metric_name)
    available = [(key.split("|")[-1], value) for key, value in values.items() if value is not None]
    ranked = sorted(available, key=lambda item: item[1], reverse=(metric == "gain"))
    return [f"{ticker} {value:.2f}%" for ticker, value in ranked[:3]]


def first_metric_by_candidate(rows: list[CatalystHeadline], metric_name: str, *, fallback: str = "") -> dict[str, float | int | None]:
    values: dict[str, float | int | None] = {}
    for row in rows:
        key = candidate_key(row)
        if key in values:
            continue
        value = getattr(row, metric_name)
        if value is None and fallback:
            value = getattr(row, fallback)
        values[key] = value
    return values


def candidate_key(row: CatalystHeadline) -> str:
    return "|".join([row.capture_date, row.capture_time, row.session, row.provider, row.scanner, row.ticker])


def synthetic_no_headline() -> dict:
    return {"headline": "No stored headline", "source": "", "url": "", "published_at": ""}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def average(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 4)


def win_rate(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round((sum(1 for value in values if value > 0) / len(values)) * 100, 2)
