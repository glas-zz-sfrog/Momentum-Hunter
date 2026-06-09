from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.replay import (
    TimelineRow,
    build_timeline_row,
    capture_sources,
    load_capture_payload,
    outcome_key,
)
from momentum_hunter.review import CandidateIdentity, load_review_decisions, make_capture_id
from momentum_hunter.scheduling import classify_capture
from momentum_hunter.score_breakdowns import COMPLETE, INCOMPLETE, LEGACY, SCORE_BREAKDOWNS_PATH, find_score_breakdown, score_breakdown_identity
from momentum_hunter.storage import CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR
from momentum_hunter.study import REGIME_ALL, SESSION_ALL, StudyFilter, parse_optional_float


CLUSTER_RESEARCH_LABEL = "HISTORICAL CLUSTERS — RESEARCH ONLY"
REVIEW_ALL = "all review statuses"
SCANNER_ALL = "all scanners"
SECTOR_ALL = "all sectors"
SAMPLE_SIZE_WARNING_LIMIT = 10


@dataclass(frozen=True)
class ClusterCandidate:
    capture_date: str
    capture_time: str
    session: str
    provider: str
    scanner: str
    ticker: str
    sector: str
    industry: str
    market_regime: str
    score: int
    review_status: str
    headlines: list[str] = field(default_factory=list)
    catalyst_keywords: list[str] = field(default_factory=list)
    score_components: list[str] = field(default_factory=list)
    max_gain_pct: float | None = None
    max_drawdown_pct: float | None = None
    next_day_return_pct: float | None = None
    five_day_return_pct: float | None = None
    outcome_status: str = "missing"
    is_study_eligible: bool = False


@dataclass(frozen=True)
class HistoricalClusterSummary:
    name: str
    candidate_count: int
    tickers: list[str]
    date_range: str
    average_score: float | None
    average_max_gain_pct: float | None
    average_max_drawdown_pct: float | None
    win_rate_pct: float | None
    top_winners: list[str]
    worst_failures: list[str]
    common_score_components: list[str]
    common_catalyst_keywords: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HistoricalClusterReport:
    label: str
    source: str
    total_candidates: int
    filters: StudyFilter
    clusters: list[HistoricalClusterSummary]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HistoricalAppearance:
    cluster_type: str
    cluster_key: str
    ticker: str
    capture_date: str
    capture_time_text: str
    session: str
    provider: str
    scanner: str
    score: int
    review_status: str
    score_breakdown_status: str
    outcome_status: str
    next_day_return_pct: float | None
    five_day_return_pct: float | None
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    trust_label: str
    warnings: list[str]
    timeline_row: TimelineRow


@dataclass(frozen=True)
class RecurrenceOutcomeSummary:
    completed_count: int
    pending_count: int
    average_next_day_return_pct: float | None
    average_five_day_return_pct: float | None
    average_max_gain_pct: float | None
    average_max_drawdown_pct: float | None


@dataclass(frozen=True)
class HistoricalRecurrenceCluster:
    cluster_type: str
    cluster_key: str
    appearance_count: int
    first_seen: str
    most_recent_seen: str
    scanners_involved: list[str]
    sessions_involved: list[str]
    average_score: float | None
    complete_score_breakdown_count: int
    incomplete_score_breakdown_count: int
    legacy_score_breakdown_count: int
    missing_score_breakdown_count: int
    outcome_summary: RecurrenceOutcomeSummary
    appearances: list[HistoricalAppearance]


@dataclass(frozen=True)
class HistoricalRecurrenceReport:
    label: str
    source: str
    total_appearances: int
    clusters: list[HistoricalRecurrenceCluster]
    warnings: list[str] = field(default_factory=list)


def build_historical_cluster_report(
    *,
    study_filter: StudyFilter | None = None,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
) -> HistoricalClusterReport:
    study_filter = study_filter or StudyFilter()
    candidates = load_cluster_candidates(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    filtered = filter_cluster_candidates(candidates, study_filter)
    grouped: dict[str, list[ClusterCandidate]] = defaultdict(list)
    for candidate in filtered:
        grouped[classify_candidate_cluster(candidate)].append(candidate)

    clusters = [
        summarize_cluster(name, rows)
        for name, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    source = "active raw captures + score-breakdowns.json + review-decisions.json + analysis-outcomes.csv"
    warnings = []
    if not candidates:
        warnings.append("No active raw capture candidates found.")
    if not filtered and candidates:
        warnings.append("Filters removed all historical candidates.")
    return HistoricalClusterReport(
        label=CLUSTER_RESEARCH_LABEL,
        source=source,
        total_candidates=len(filtered),
        filters=study_filter,
        clusters=clusters,
        warnings=warnings,
    )


def build_historical_recurrence_report(
    *,
    study_filter: StudyFilter | None = None,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
    include_quarantined: bool = False,
) -> HistoricalRecurrenceReport:
    study_filter = study_filter or StudyFilter()
    appearances = load_historical_appearances(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
        include_quarantined=include_quarantined,
    )
    filtered = filter_historical_appearances(appearances, study_filter)
    clusters: list[HistoricalRecurrenceCluster] = []
    for cluster_type in ["ticker", "sector", "scanner"]:
        grouped: dict[str, list[HistoricalAppearance]] = defaultdict(list)
        for appearance in filtered:
            grouped[cluster_key_for_type(appearance, cluster_type)].append(
                HistoricalAppearance(
                    cluster_type=cluster_type,
                    cluster_key=cluster_key_for_type(appearance, cluster_type),
                    ticker=appearance.ticker,
                    capture_date=appearance.capture_date,
                    capture_time_text=appearance.capture_time_text,
                    session=appearance.session,
                    provider=appearance.provider,
                    scanner=appearance.scanner,
                    score=appearance.score,
                    review_status=appearance.review_status,
                    score_breakdown_status=appearance.score_breakdown_status,
                    outcome_status=appearance.outcome_status,
                    next_day_return_pct=appearance.next_day_return_pct,
                    five_day_return_pct=appearance.five_day_return_pct,
                    max_gain_pct=appearance.max_gain_pct,
                    max_drawdown_pct=appearance.max_drawdown_pct,
                    trust_label=appearance.trust_label,
                    warnings=appearance.warnings,
                    timeline_row=appearance.timeline_row,
                )
            )
        for key, rows in grouped.items():
            if len(rows) < 2:
                continue
            clusters.append(summarize_recurrence_cluster(cluster_type, key, rows))

    clusters.sort(key=lambda cluster: (cluster.appearance_count, cluster.most_recent_seen, cluster.average_score or 0), reverse=True)
    warnings = []
    if not appearances:
        warnings.append("No trusted historical appearances found.")
    if appearances and not filtered:
        warnings.append("Filters removed all historical appearances.")
    if filtered and not clusters:
        warnings.append("No repeated ticker, sector, or scanner clusters matched the filters.")
    return HistoricalRecurrenceReport(
        label="HISTORICAL CLUSTERS - RECURRING APPEARANCES",
        source="active raw captures + replay identities + score-breakdowns.json + review-decisions.json + analysis-outcomes.csv",
        total_appearances=len(filtered),
        clusters=clusters,
        warnings=warnings,
    )


def load_historical_appearances(
    *,
    captures_dir: Path,
    manifest_path: Path,
    score_breakdowns_path: Path,
    review_decisions_path: Path,
    outcomes_csv: Path,
    include_quarantined: bool,
) -> list[HistoricalAppearance]:
    review_decisions = load_review_decisions(review_decisions_path)
    outcomes = load_outcome_rows(outcomes_csv)
    appearances: list[HistoricalAppearance] = []
    for capture_path, quarantined in capture_sources(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        include_quarantined=include_quarantined,
    ):
        payload = load_capture_payload(capture_path)
        if not payload:
            continue
        for candidate in payload.get("candidates", []):
            row = build_timeline_row(
                payload,
                candidate,
                capture_path=capture_path,
                quarantined=quarantined,
                score_breakdowns_path=score_breakdowns_path,
                review_decisions=review_decisions,
                outcomes=outcomes,
            )
            appearances.append(appearance_from_timeline_row(row))
    appearances.sort(key=lambda item: (item.timeline_row.capture_time or "", item.ticker, item.session, item.scanner))
    return appearances


def appearance_from_timeline_row(row: TimelineRow) -> HistoricalAppearance:
    sector = str(row.fields.get("sector").value if row.fields.get("sector") else "unknown") or "unknown"
    score = parse_int(row.fields.get("score").value if row.fields.get("score") else 0)
    return HistoricalAppearance(
        cluster_type="candidate",
        cluster_key=sector,
        ticker=row.ticker.upper(),
        capture_date=row.capture_date,
        capture_time_text=row.capture_time_text,
        session=row.session,
        provider=row.provider,
        scanner=row.scanner,
        score=score,
        review_status=str(row.fields.get("review_status").value if row.fields.get("review_status") else "unreviewed"),
        score_breakdown_status=str(row.fields.get("score_breakdown_status").value if row.fields.get("score_breakdown_status") else "missing"),
        outcome_status=str(row.fields.get("outcome_status").value if row.fields.get("outcome_status") else "missing"),
        next_day_return_pct=parse_optional_float(row.fields.get("next_day_return_pct").value if row.fields.get("next_day_return_pct") else ""),
        five_day_return_pct=parse_optional_float(row.fields.get("five_day_return_pct").value if row.fields.get("five_day_return_pct") else ""),
        max_gain_pct=parse_optional_float(row.fields.get("max_gain_pct").value if row.fields.get("max_gain_pct") else ""),
        max_drawdown_pct=parse_optional_float(row.fields.get("max_drawdown_pct").value if row.fields.get("max_drawdown_pct") else ""),
        trust_label=row.trust_label,
        warnings=list(row.warnings),
        timeline_row=row,
    )


def filter_historical_appearances(appearances: list[HistoricalAppearance], study_filter: StudyFilter) -> list[HistoricalAppearance]:
    filtered = appearances
    if not study_filter.include_non_study_eligible:
        filtered = [appearance for appearance in filtered if appearance.timeline_row.calendar_classification.is_study_eligible]
    if study_filter.start_date:
        filtered = [appearance for appearance in filtered if appearance.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [appearance for appearance in filtered if appearance.capture_date <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [appearance for appearance in filtered if appearance.session == study_filter.session]
    if study_filter.regime != REGIME_ALL:
        filtered = [
            appearance
            for appearance in filtered
            if str(appearance.timeline_row.fields.get("market_regime").value if appearance.timeline_row.fields.get("market_regime") else "unknown").lower() == study_filter.regime
        ]
    if study_filter.scanner != SCANNER_ALL:
        filtered = [appearance for appearance in filtered if appearance.scanner == study_filter.scanner]
    if study_filter.sector != SECTOR_ALL:
        filtered = [appearance for appearance in filtered if cluster_key_for_type(appearance, "sector") == study_filter.sector]
    if study_filter.minimum_score:
        filtered = [appearance for appearance in filtered if appearance.score >= study_filter.minimum_score]
    if study_filter.review_status != REVIEW_ALL:
        filtered = [appearance for appearance in filtered if appearance.review_status == study_filter.review_status]
    if study_filter.ticker:
        filtered = [appearance for appearance in filtered if appearance.ticker == study_filter.ticker.upper()]
    return filtered


def cluster_key_for_type(appearance: HistoricalAppearance, cluster_type: str) -> str:
    if cluster_type == "ticker":
        return appearance.ticker
    if cluster_type == "scanner":
        return appearance.scanner or "unknown"
    if cluster_type == "sector":
        row = appearance.timeline_row
        return str(row.fields.get("sector").value if row.fields.get("sector") else "unknown") or "unknown"
    return "unknown"


def summarize_recurrence_cluster(cluster_type: str, key: str, rows: list[HistoricalAppearance]) -> HistoricalRecurrenceCluster:
    ordered = sorted(rows, key=lambda row: (row.timeline_row.capture_time or "", row.ticker, row.session, row.scanner))
    status_counts = Counter(normalize_breakdown_status(row.score_breakdown_status) for row in ordered)
    completed_rows = [row for row in ordered if row.outcome_status == "complete"]
    pending_rows = [row for row in ordered if row.outcome_status != "complete"]
    return HistoricalRecurrenceCluster(
        cluster_type=cluster_type,
        cluster_key=key,
        appearance_count=len(ordered),
        first_seen=ordered[0].capture_time_text,
        most_recent_seen=ordered[-1].capture_time_text,
        scanners_involved=sorted({row.scanner for row in ordered if row.scanner}),
        sessions_involved=sorted({row.session for row in ordered if row.session}),
        average_score=average([row.score for row in ordered]),
        complete_score_breakdown_count=status_counts[COMPLETE],
        incomplete_score_breakdown_count=status_counts[INCOMPLETE],
        legacy_score_breakdown_count=status_counts[LEGACY],
        missing_score_breakdown_count=status_counts["missing"],
        outcome_summary=RecurrenceOutcomeSummary(
            completed_count=len(completed_rows),
            pending_count=len(pending_rows),
            average_next_day_return_pct=average([row.next_day_return_pct for row in completed_rows if row.next_day_return_pct is not None]),
            average_five_day_return_pct=average([row.five_day_return_pct for row in completed_rows if row.five_day_return_pct is not None]),
            average_max_gain_pct=average([row.max_gain_pct for row in completed_rows if row.max_gain_pct is not None]),
            average_max_drawdown_pct=average([row.max_drawdown_pct for row in completed_rows if row.max_drawdown_pct is not None]),
        ),
        appearances=ordered,
    )


def normalize_breakdown_status(value: str) -> str:
    normalized = (value or "missing").lower()
    if normalized in {COMPLETE, INCOMPLETE, LEGACY}:
        return normalized
    return "missing"


def load_cluster_candidates(
    *,
    captures_dir: Path,
    score_breakdowns_path: Path,
    review_decisions_path: Path,
    outcomes_csv: Path,
) -> list[ClusterCandidate]:
    review_decisions = load_review_decisions(review_decisions_path)
    outcomes = load_outcome_rows(outcomes_csv)
    candidates: list[ClusterCandidate] = []
    for capture_path in sorted(captures_dir.rglob("*.json")):
        payload = load_json(capture_path)
        if not payload:
            continue
        capture_time = payload.get("capture_time", "")
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
            headlines = candidate_headlines(candidate_payload)
            keywords = catalyst_keywords_for_text(" ".join(headlines + [str(candidate_payload.get("score_reasons", ""))]))
            components = common_component_labels(breakdown)
            sector = str(candidate_payload.get("sector", "") or "unknown")
            if sector_counts.get(sector, 0) >= 2 and not keywords:
                keywords.append("sector sympathy")
            candidates.append(
                ClusterCandidate(
                    capture_date=capture_date,
                    capture_time=capture_time,
                    session=session,
                    provider=provider,
                    scanner=scanner,
                    ticker=ticker,
                    sector=sector,
                    industry=str(candidate_payload.get("industry", "") or "unknown"),
                    market_regime=market_regime,
                    score=parse_int(candidate_payload.get("score")),
                    review_status=review.review_status.value if review else "unreviewed",
                    headlines=headlines,
                    catalyst_keywords=sorted(set(keywords)),
                    score_components=components,
                    max_gain_pct=parse_optional_float(outcome.get("max_gain_pct", "")),
                    max_drawdown_pct=parse_optional_float(outcome.get("max_drawdown_pct", "")),
                    next_day_return_pct=parse_optional_float(outcome.get("next_day_return_pct", "")),
                    five_day_return_pct=parse_optional_float(outcome.get("five_day_return_pct", "")),
                    outcome_status=outcome.get("outcome_status", "missing") if outcome else "missing",
                    is_study_eligible=classification.is_study_eligible,
                )
            )
    return candidates


def filter_cluster_candidates(candidates: list[ClusterCandidate], study_filter: StudyFilter) -> list[ClusterCandidate]:
    filtered = candidates
    if not study_filter.include_non_study_eligible:
        filtered = [candidate for candidate in filtered if candidate.is_study_eligible]
    if study_filter.start_date:
        filtered = [candidate for candidate in filtered if candidate.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [candidate for candidate in filtered if candidate.capture_date <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [candidate for candidate in filtered if candidate.session == study_filter.session]
    if study_filter.regime != REGIME_ALL:
        filtered = [candidate for candidate in filtered if candidate.market_regime == study_filter.regime]
    if study_filter.scanner != SCANNER_ALL:
        filtered = [candidate for candidate in filtered if candidate.scanner == study_filter.scanner]
    if study_filter.sector != SECTOR_ALL:
        filtered = [candidate for candidate in filtered if candidate.sector == study_filter.sector]
    if study_filter.minimum_score:
        filtered = [candidate for candidate in filtered if candidate.score >= study_filter.minimum_score]
    if study_filter.review_status != REVIEW_ALL:
        filtered = [candidate for candidate in filtered if candidate.review_status == study_filter.review_status]
    return filtered


def classify_candidate_cluster(candidate: ClusterCandidate) -> str:
    keywords = set(candidate.catalyst_keywords)
    sector = candidate.sector.lower()
    industry = candidate.industry.lower()
    if keywords & {"fda", "approval", "phase 3", "trial"} or "biotech" in industry:
        return "Healthcare / FDA / biotech"
    if keywords & {"earnings", "beat", "guidance", "outlook", "revenue", "eps"}:
        return "Earnings / guidance"
    if keywords & {"upgrade", "downgrade", "analyst", "price target"}:
        return "Analyst upgrade / downgrade"
    if keywords & {"ai", "data center", "server", "gpu", "semiconductor"}:
        return "AI infrastructure"
    if keywords & {"meme", "reddit", "short squeeze", "social media", "speculation"}:
        return "Low-quality hype / weak catalyst"
    if "sector sympathy" in keywords:
        return "Sector sympathy move"
    if candidate.score >= 85 and ("Volume" in candidate.score_components or "Market Cap" in candidate.score_components):
        return "High volume institutional momentum"
    return "No clear catalyst"


def summarize_cluster(name: str, rows: list[ClusterCandidate]) -> HistoricalClusterSummary:
    dates = sorted({row.capture_date for row in rows if row.capture_date})
    max_gains = [row.max_gain_pct for row in rows if row.max_gain_pct is not None]
    drawdowns = [row.max_drawdown_pct for row in rows if row.max_drawdown_pct is not None]
    win_values = [
        value
        for row in rows
        for value in [row.five_day_return_pct if row.five_day_return_pct is not None else row.next_day_return_pct]
        if value is not None
    ]
    missing_outcomes = sum(1 for row in rows if row.outcome_status == "missing" or row.max_gain_pct is None)
    warnings = []
    if len(rows) < SAMPLE_SIZE_WARNING_LIMIT:
        warnings.append(f"Sample size {len(rows)} - diagnostic only.")
    if missing_outcomes:
        warnings.append(f"Missing outcome data for {missing_outcomes} candidate(s); metrics use available rows only.")
    return HistoricalClusterSummary(
        name=name,
        candidate_count=len(rows),
        tickers=sorted({row.ticker for row in rows}),
        date_range=f"{dates[0]} to {dates[-1]}" if dates else "unknown",
        average_score=average([row.score for row in rows]),
        average_max_gain_pct=average(max_gains),
        average_max_drawdown_pct=average(drawdowns),
        win_rate_pct=win_rate(win_values),
        top_winners=ranked_tickers(rows, "gain"),
        worst_failures=ranked_tickers(rows, "drawdown"),
        common_score_components=top_counter_items(row.score_components for row in rows),
        common_catalyst_keywords=top_counter_items(row.catalyst_keywords for row in rows),
        warnings=warnings,
    )


def candidate_headlines(candidate_payload: dict) -> list[str]:
    news = candidate_payload.get("news", [])
    if not isinstance(news, list):
        return []
    return [
        str(item.get("headline", "")).strip()
        for item in news
        if isinstance(item, dict) and str(item.get("headline", "")).strip()
    ]


def catalyst_keywords_for_text(text: str) -> list[str]:
    lowered = text.lower()
    keyword_groups = {
        "earnings": ["earnings", "eps", "quarterly results"],
        "beat": ["beat", "beats", "tops", "record revenue"],
        "guidance": ["guidance", "outlook", "forecast", "raises"],
        "revenue": ["revenue", "sales"],
        "fda": ["fda"],
        "approval": ["approval", "approved", "clearance"],
        "phase 3": ["phase 3", "phase iii"],
        "trial": ["trial", "study"],
        "upgrade": ["upgrade", "raised target", "price target"],
        "downgrade": ["downgrade", "cut target"],
        "analyst": ["analyst", "initiates"],
        "ai": [" ai ", "artificial intelligence", " ai-", " ai."],
        "data center": ["data center", "datacenter"],
        "server": ["server", "servers"],
        "gpu": ["gpu", "accelerator"],
        "semiconductor": ["semiconductor", "chip"],
        "meme": ["meme"],
        "reddit": ["reddit"],
        "short squeeze": ["short squeeze", "squeeze"],
        "social media": ["social media"],
        "speculation": ["rumor", "speculation", "hype"],
    }
    padded = f" {lowered} "
    matches = []
    for label, needles in keyword_groups.items():
        if any(needle in padded for needle in needles):
            matches.append(label)
    return matches


def common_component_labels(score_breakdown: dict | None) -> list[str]:
    if not score_breakdown:
        return []
    labels = []
    for component in score_breakdown.get("components", []):
        if not isinstance(component, dict):
            continue
        contribution = parse_int(component.get("points_after_adjustment"))
        label = str(component.get("label") or component.get("key") or "").strip()
        if label and contribution > 0:
            labels.append(label)
    return labels


def ranked_tickers(rows: list[ClusterCandidate], metric: str) -> list[str]:
    if metric == "gain":
        available = [(row.ticker, row.max_gain_pct) for row in rows if row.max_gain_pct is not None]
        ranked = sorted(available, key=lambda item: item[1], reverse=True)
    else:
        available = [(row.ticker, row.max_drawdown_pct) for row in rows if row.max_drawdown_pct is not None]
        ranked = sorted(available, key=lambda item: item[1])
    return [f"{ticker} {value:.2f}%" for ticker, value in ranked[:3]]


def top_counter_items(values: list[list[str]], limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for row_values in values:
        counter.update(row_values)
    return [f"{label} ({count})" for label, count in counter.most_common(limit)]


def load_outcome_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as file:
        return {
            outcome_key(
                row.get("capture_date", ""),
                row.get("capture_time", ""),
                row.get("session", ""),
                row.get("provider", ""),
                row.get("scanner", ""),
                row.get("ticker", ""),
            ): row
            for row in csv.DictReader(file)
        }


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scanner_name(payload: dict) -> str:
    scanner = payload.get("scanner", {})
    return scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)


def parse_int(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def average(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 4)


def win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round((sum(1 for value in values if value > 0) / len(values)) * 100, 2)
