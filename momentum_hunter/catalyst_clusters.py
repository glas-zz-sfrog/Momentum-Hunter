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
from momentum_hunter.study import CATALYST_CLUSTER_ALL, REGIME_ALL, REVIEW_ALL, SESSION_ALL, StudyFilter, parse_optional_float


CATALYST_RESEARCH_LABEL = "CATALYST CLUSTERS — RESEARCH ONLY"
HISTORICAL_THEME_ALL = "all historical themes"
SAMPLE_SIZE_WARNING_LIMIT = 10
LOW_CONFIDENCE_WARNING_SCORE = 60
LOW_PURITY_WARNING_PCT = 60.0
HIGH_UNKNOWN_TIMESTAMP_WARNING_PCT = 40.0
HIGH_FUTURE_TIMESTAMP_WARNING_PCT = 5.0


@dataclass(frozen=True)
class CatalystClassification:
    cluster_name: str
    confidence_score: int
    confidence_label: str
    rule_name: str
    match_type: str
    fallback_reason: str = ""


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
    classification_confidence: str
    classification_confidence_score: int
    classification_rule: str
    classification_match_type: str
    fallback_reason: str
    score_components: list[str] = field(default_factory=list)
    is_study_eligible: bool = False


@dataclass(frozen=True)
class TimestampQualitySummary:
    group: str
    headline_count: int
    exact_count: int
    unknown_count: int
    future_count: int
    invalid_count: int
    exact_pct: float
    unknown_pct: float
    future_pct: float
    invalid_pct: float
    warnings: list[str] = field(default_factory=list)


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
    average_confidence_score: float | None
    dominant_confidence: str
    purity_pct: float
    explicit_match_count: int
    fallback_match_count: int
    explicit_match_pct: float
    timestamp_quality: TimestampQualitySummary
    common_rules: list[str]
    fallback_reasons: list[str]
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
    provider_quality: list[TimestampQualitySummary]
    cluster_quality: list[TimestampQualitySummary]
    ticker_quality: list[TimestampQualitySummary]
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
    headlines, _future_count = load_catalyst_headlines(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    filtered = filter_catalyst_headlines(headlines, study_filter)
    excluded_future_count = sum(1 for headline in filtered if headline.timestamp_status == "future")
    cluster_rows = [headline for headline in filtered if headline.timestamp_status != "future"]
    grouped: dict[str, list[CatalystHeadline]] = defaultdict(list)
    for headline in cluster_rows:
        grouped[headline.cluster_name].append(headline)

    clusters = filter_cluster_summaries(
        [
        summarize_catalyst_cluster(name, rows)
        for name, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
        study_filter,
    )
    warnings = []
    if excluded_future_count:
        warnings.append(f"Excluded {excluded_future_count} future-timestamp headline(s) from catalyst clustering.")
    if not headlines:
        warnings.append("No stored historical headlines found in active raw captures.")
    if not cluster_rows and headlines:
        warnings.append("Filters removed all stored historical headlines.")
    return CatalystClusterReport(
        label=CATALYST_RESEARCH_LABEL,
        source="active raw captures + score-breakdowns.json + review-decisions.json + analysis-outcomes.csv + catalyst age metrics",
        total_headlines=sum(cluster.headline_count for cluster in clusters),
        total_candidates=len({candidate_key(headline) for cluster in clusters for headline in cluster.headlines}),
        excluded_future_headlines=excluded_future_count,
        filters=study_filter,
        clusters=clusters,
        provider_quality=summarize_timestamp_quality_by(filtered, "provider"),
        cluster_quality=summarize_timestamp_quality_by(filtered, "cluster_name"),
        ticker_quality=summarize_timestamp_quality_by(filtered, "ticker"),
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
        capture_classification = classify_capture(capture_time, session, capture_date=capture_date)
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
                is_study_eligible=capture_classification.is_study_eligible,
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
                catalyst_classification = classify_catalyst_headline_detail(
                    headline,
                    sector=sector,
                    industry=str(candidate_payload.get("industry", "")),
                    sector_sympathy=sector_counts.get(sector, 0) >= 2,
                )
                rows.append(
                    CatalystHeadline(
                        cluster_name=catalyst_classification.cluster_name,
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
                        classification_confidence=catalyst_classification.confidence_label,
                        classification_confidence_score=catalyst_classification.confidence_score,
                        classification_rule=catalyst_classification.rule_name,
                        classification_match_type=catalyst_classification.match_type,
                        fallback_reason=catalyst_classification.fallback_reason,
                        score_components=common_component_labels(breakdown),
                        is_study_eligible=capture_classification.is_study_eligible,
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
    if study_filter.ticker:
        filtered = [headline for headline in filtered if headline.ticker == study_filter.ticker.upper()]
    if study_filter.catalyst_cluster != CATALYST_CLUSTER_ALL:
        filtered = [headline for headline in filtered if headline.cluster_name == study_filter.catalyst_cluster]
    if study_filter.minimum_confidence:
        filtered = [headline for headline in filtered if headline.classification_confidence_score >= study_filter.minimum_confidence]
    return filtered


def filter_cluster_summaries(clusters: list[CatalystClusterSummary], study_filter: StudyFilter) -> list[CatalystClusterSummary]:
    filtered = clusters
    if study_filter.minimum_purity:
        filtered = [cluster for cluster in filtered if cluster.purity_pct >= study_filter.minimum_purity]
    if study_filter.minimum_timestamp_quality:
        filtered = [cluster for cluster in filtered if cluster.timestamp_quality.exact_pct >= study_filter.minimum_timestamp_quality]
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
    explicit_match_count = sum(1 for row in rows if row.classification_match_type == "explicit")
    fallback_match_count = len(rows) - explicit_match_count
    explicit_match_pct = percent(explicit_match_count, len(rows))
    purity_pct = explicit_match_pct
    timestamp_quality = summarize_timestamp_quality(name, rows)
    confidence_scores = [row.classification_confidence_score for row in rows]
    average_confidence_score = average(confidence_scores)
    dominant_confidence = most_common_text([row.classification_confidence for row in rows], default="unknown")
    if average_confidence_score is not None and average_confidence_score < LOW_CONFIDENCE_WARNING_SCORE:
        warnings.append("LOW CONFIDENCE CLUSTER")
    if purity_pct < LOW_PURITY_WARNING_PCT:
        warnings.append("LOW PURITY CLUSTER")
    warnings.extend(timestamp_quality.warnings)
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
        average_confidence_score=average_confidence_score,
        dominant_confidence=dominant_confidence,
        purity_pct=purity_pct,
        explicit_match_count=explicit_match_count,
        fallback_match_count=fallback_match_count,
        explicit_match_pct=explicit_match_pct,
        timestamp_quality=timestamp_quality,
        common_rules=common_text_values([row.classification_rule for row in rows], limit=5),
        fallback_reasons=common_text_values([row.fallback_reason for row in rows if row.fallback_reason], limit=5),
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
    return classify_catalyst_headline_detail(
        headline,
        sector=sector,
        industry=industry,
        sector_sympathy=sector_sympathy,
    ).cluster_name


def classify_catalyst_headline_detail(headline: str, *, sector: str, industry: str, sector_sympathy: bool) -> CatalystClassification:
    lowered = headline.lower()
    if any_term(lowered, ["beats", "beat estimates", "tops estimates", "eps beat", "earnings beat", "record revenue"]):
        return explicit_classification("Earnings beat", 95, "earnings_beat")
    if any_term(lowered, ["raises guidance", "raised guidance", "guidance raise", "raises outlook", "boosts outlook"]):
        return explicit_classification("Guidance raise", 93, "guidance_raise")
    if any_term(lowered, ["earnings", "eps", "quarterly results", "guidance", "outlook"]):
        return explicit_classification("Earnings/guidance general", 78, "earnings_guidance_general")
    if any_term(lowered, ["upgrade", "upgraded", "initiated at buy", "initiates buy"]):
        return explicit_classification("Analyst upgrade", 90, "analyst_upgrade")
    if any_term(lowered, ["price target", "target raise", "raised target", "target lifted", "raises target"]):
        return explicit_classification("Analyst target raise", 86, "analyst_target_raise")
    if any_term(lowered, ["downgrade", "downgraded", "cut to sell", "lowered rating"]):
        return explicit_classification("Analyst downgrade", 90, "analyst_downgrade")
    if any_term(lowered, ["ai partnership", "artificial intelligence partnership"]):
        return explicit_classification("AI partnership", 92, "ai_partnership")
    if any_term(f" {lowered} ", [" ai ", "artificial intelligence", "data center", "datacenter", "server", "gpu", "semiconductor", "accelerator chip"]):
        return explicit_classification("AI infrastructure", 82, "ai_infrastructure")
    if any_term(lowered, ["contract", "customer win", "award", "partnership", "deal with", "selected by", "multi-year agreement"]):
        return explicit_classification("Contract / customer win", 84, "contract_customer_win")
    if any_term(lowered, ["fda approval", "fda approves", "approved by fda", "clearance"]):
        return explicit_classification("FDA approval", 95, "fda_approval")
    if any_term(lowered, ["fda", "pdufa", "complete response", "resubmission"]):
        return explicit_classification("FDA binary event", 88, "fda_binary_event")
    if any_term(lowered, ["phase 3", "phase iii", "clinical", "trial data", "study results"]):
        return explicit_classification("Biotech clinical data", 86, "biotech_clinical_data")
    if any_term(lowered, ["acquisition", "acquires", "merger", "buyout", "takeover"]):
        return explicit_classification("Merger / acquisition", 94, "merger_acquisition")
    if any_term(lowered, ["launches", "launch", "unveils", "introduces", "rolls out", "new product", "platform"]):
        return explicit_classification("Product / platform launch", 76, "product_platform_launch")
    if any_term(lowered, ["offering", "share sale", "secondary", "convertible notes", "buyback", "repurchase", "debt offering"]):
        return explicit_classification("Capital markets / financing", 78, "capital_markets_financing")
    if any_term(lowered, ["lawsuit", "settlement", "sec investigation", "investigation", "antitrust", "regulatory probe"]):
        return explicit_classification("Legal / regulatory", 78, "legal_regulatory")
    if any_term(lowered, ["ceo", "cfo", "board", "restructuring", "layoffs", "strategic review"]):
        return explicit_classification("Leadership / strategic update", 72, "leadership_strategic_update")
    if any_term(lowered, ["joins s&p", "s&p 500", "nasdaq 100", "index inclusion", "added to index"]):
        return explicit_classification("Index / fund flow", 80, "index_fund_flow")
    if any_term(lowered, ["fed", "inflation", "tariff", "jobs report", "cpi", "macro"]):
        return explicit_classification("Macro-only", 76, "macro_only")
    if any_term(lowered, ["rumor", "speculation", "meme", "reddit", "short squeeze", "hype"]):
        return explicit_classification("Weak / vague catalyst", 72, "weak_vague_explicit")
    if any_term(lowered, ["stock jumps", "stock rises", "shares rise", "shares jump", "stock falls", "shares fall", "why", "moving today", "stock moves"]):
        return explicit_classification("Price action / no catalyst detail", 58, "price_action_only")
    if sector_sympathy:
        return fallback_classification("Sector sympathy", 45, "sector_sympathy_fallback", "No explicit catalyst terms; ticker appeared with same-sector candidates.")
    if not headline or headline == "No stored headline":
        return fallback_classification("No clear catalyst", 20, "no_stored_headline", "No stored headline text was available.")
    return fallback_classification("Unknown / uncategorized", 35, "unknown_uncategorized", "Headline did not match any explicit v2 rule.")


def explicit_classification(cluster_name: str, score: int, rule_name: str) -> CatalystClassification:
    return CatalystClassification(
        cluster_name=cluster_name,
        confidence_score=score,
        confidence_label=confidence_label(score),
        rule_name=rule_name,
        match_type="explicit",
    )


def fallback_classification(cluster_name: str, score: int, rule_name: str, reason: str) -> CatalystClassification:
    return CatalystClassification(
        cluster_name=cluster_name,
        confidence_score=score,
        confidence_label=confidence_label(score),
        rule_name=rule_name,
        match_type="fallback",
        fallback_reason=reason,
    )


def confidence_label(score: int) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def any_term(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


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
        "Contract / customer win": ["contract"],
        "FDA approval": ["fda", "approval"],
        "FDA binary event": ["fda"],
        "Biotech clinical data": ["trial"],
        "Product / platform launch": ["launch"],
        "Capital markets / financing": ["financing"],
        "Legal / regulatory": ["regulatory"],
        "Leadership / strategic update": ["leadership"],
        "Index / fund flow": ["index"],
        "Price action / no catalyst detail": ["price action"],
        "Weak / vague catalyst": ["speculation"],
        "Sector sympathy": ["sector sympathy"],
    }
    return compatibility.get(cluster, [])


def timestamp_status_and_age(published_at: object, capture_dt: datetime | None) -> tuple[str, float | None]:
    if not published_at:
        return "unknown", None
    published_dt = parse_datetime(str(published_at))
    if published_dt is None:
        return "invalid", None
    if capture_dt is None:
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


def summarize_timestamp_quality_by(rows: list[CatalystHeadline], field_name: str) -> list[TimestampQualitySummary]:
    grouped: dict[str, list[CatalystHeadline]] = defaultdict(list)
    for row in rows:
        grouped[getattr(row, field_name)].append(row)
    summaries = [summarize_timestamp_quality(name or "unknown", grouped_rows) for name, grouped_rows in grouped.items()]
    return sorted(summaries, key=lambda item: (-item.headline_count, item.group))


def summarize_timestamp_quality(group: str, rows: list[CatalystHeadline]) -> TimestampQualitySummary:
    total = len(rows)
    exact_count = sum(1 for row in rows if row.timestamp_status == "known")
    unknown_count = sum(1 for row in rows if row.timestamp_status == "unknown")
    future_count = sum(1 for row in rows if row.timestamp_status == "future")
    invalid_count = sum(1 for row in rows if row.timestamp_status == "invalid")
    unknown_pct = percent(unknown_count, total)
    future_pct = percent(future_count, total)
    warnings = []
    if unknown_pct >= HIGH_UNKNOWN_TIMESTAMP_WARNING_PCT and unknown_count:
        warnings.append("HIGH UNKNOWN TIMESTAMP RATE")
    if future_pct >= HIGH_FUTURE_TIMESTAMP_WARNING_PCT and future_count:
        warnings.append("HIGH FUTURE TIMESTAMP RATE")
    return TimestampQualitySummary(
        group=group,
        headline_count=total,
        exact_count=exact_count,
        unknown_count=unknown_count,
        future_count=future_count,
        invalid_count=invalid_count,
        exact_pct=percent(exact_count, total),
        unknown_pct=unknown_pct,
        future_pct=future_pct,
        invalid_pct=percent(invalid_count, total),
        warnings=warnings,
    )


def common_text_values(values: list[str], limit: int = 5) -> list[str]:
    counts = Counter(value for value in values if value)
    return [value for value, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def most_common_text(values: list[str], *, default: str = "") -> str:
    common = common_text_values(values, limit=1)
    return common[0] if common else default


def percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


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
