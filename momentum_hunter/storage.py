from __future__ import annotations

import copy
import hashlib
import json
import re
import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import Candidate, CaptureSession, MarketRegime, NewsItem, NewsStack, ScannerCriteria, TradingMode
from momentum_hunter.news_age import apply_candidate_news_stack, filter_news_known_at_capture, format_news_age, format_news_range
from momentum_hunter.time_utils import now_central


CAPTURES_DIR = DATA_DIR / "captures"
ANALYSIS_CSV = DATA_DIR / "analysis-captures.csv"
CAPTURE_FAILURES_DIR = DATA_DIR / "capture-failures"
INTEGRITY_DIR = DATA_DIR / "integrity"
CAPTURE_INTEGRITY_MANIFEST = INTEGRITY_DIR / "capture_manifest.json"
CAPTURE_VERSION = "raw-capture-v2"
ANALYSIS_FIELDNAMES = [
    "capture_date",
    "capture_time",
    "session",
    "mode",
    "provider",
    "scanner",
    "market_regime",
    "market_symbol",
    "market_close",
    "market_sma_50",
    "market_sma_200",
    "rank",
    "selected",
    "reviewed",
    "ticker",
    "company",
    "score",
    "news_hours_old",
    "freshness",
    "freshness_score",
    "article_count",
    "valid_timestamp_count",
    "known_timestamp_count",
    "unknown_timestamp_count",
    "future_timestamp_count",
    "excluded_from_scoring_count",
    "latest_article_age_hours",
    "oldest_article_age_hours",
    "news_range",
    "freshest_headline",
    "score_profile",
    "score_regime",
    "score_reasons",
    "price",
    "percent_change",
    "volume",
    "relative_volume",
    "market_cap",
    "sector",
    "industry",
    "user_notes",
]


class RawCaptureAlreadyExistsError(FileExistsError):
    pass


def watchlist_path(for_date: datetime | None = None) -> Path:
    ensure_app_dirs()
    value = for_date or now_central()
    return DATA_DIR / f"watchlist-{value.strftime('%Y-%m-%d')}.json"


def save_watchlist(candidates: list[Candidate], for_date: datetime | None = None) -> Path:
    path = watchlist_path(for_date)
    payload = [candidate_to_dict(candidate) for candidate in candidates]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def report_path(for_date: datetime | None = None) -> Path:
    ensure_app_dirs()
    value = for_date or now_central()
    return DATA_DIR / f"watchlist-report-{value.strftime('%Y-%m-%d')}.md"


def snapshot_path(for_date: datetime | None = None, label: str = "session") -> Path:
    ensure_app_dirs()
    value = for_date or now_central()
    safe_label = label.replace(" ", "-").lower()
    return DATA_DIR / f"snapshot-{value.strftime('%Y-%m-%d-%H%M')}-{safe_label}.md"


def capture_dir(for_date: datetime | None = None) -> Path:
    ensure_app_dirs()
    value = for_date or now_central()
    path = CAPTURES_DIR / value.strftime("%Y-%m-%d")
    path.mkdir(parents=True, exist_ok=True)
    return path


def capture_json_path(for_date: datetime | None = None, session: CaptureSession = CaptureSession.MANUAL) -> Path:
    return capture_dir(for_date) / f"{session.value}.json"


def capture_report_path(for_date: datetime | None = None, session: CaptureSession = CaptureSession.MANUAL) -> Path:
    return capture_dir(for_date) / f"{session.value}.md"


def capture_manifest_key(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_capture_integrity_manifest(path: Path | None = None) -> dict:
    path = path or CAPTURE_INTEGRITY_MANIFEST
    if not path.exists():
        return {"schema_version": 2, "records": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_capture_integrity_manifest(payload: dict, path: Path | None = None) -> Path:
    path = path or CAPTURE_INTEGRITY_MANIFEST
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def record_raw_capture_integrity(
    *,
    json_path: Path,
    report_path: Path,
    capture_time: datetime,
    session: CaptureSession,
    provider: str,
    scanner: str,
    created_at: datetime,
) -> None:
    manifest = load_capture_integrity_manifest()
    manifest["schema_version"] = 2
    records = manifest.setdefault("records", {})
    for path, kind in ((json_path, "raw_capture_json"), (report_path, "raw_capture_markdown")):
        records[capture_manifest_key(path)] = {
            "kind": kind,
            "capture_version": CAPTURE_VERSION,
            "created_at": created_at.isoformat(),
            "capture_time": capture_time.isoformat(),
            "capture_date": capture_time.strftime("%Y-%m-%d"),
            "session": session.value,
            "provider": provider,
            "scanner": scanner,
            "hash_algorithm": "sha256",
            "source_hash": file_sha256(path),
        }
    manifest["updated_at"] = now_central().isoformat()
    save_capture_integrity_manifest(manifest)


def write_raw_text_once(path: Path, text: str) -> None:
    if path.exists():
        raise RawCaptureAlreadyExistsError(f"Raw capture already exists and will not be overwritten: {path}")
    path.write_text(text, encoding="utf-8")


def capture_failure_path(failure_time: datetime | None = None, session: CaptureSession = CaptureSession.MANUAL) -> Path:
    ensure_app_dirs()
    failure_time = failure_time or now_central()
    CAPTURE_FAILURES_DIR.mkdir(parents=True, exist_ok=True)
    safe_session = session.value if isinstance(session, CaptureSession) else str(session)
    return CAPTURE_FAILURES_DIR / f"{failure_time.strftime('%Y-%m-%d-%H%M%S')}-{safe_session}.json"


def save_capture_failure(
    *,
    session: CaptureSession,
    provider: str,
    scanner: str,
    error_message: str,
    exception_type: str,
    traceback_text: str,
    failure_time: datetime | None = None,
) -> Path:
    failure_time = failure_time or now_central()
    payload = {
        "schema_version": 1,
        "status": "failure",
        "failure_time": failure_time.isoformat(),
        "session": session.value,
        "provider": provider,
        "scanner": scanner,
        "error_message": error_message,
        "exception_type": exception_type,
        "traceback": traceback_text,
    }
    path = capture_failure_path(failure_time, session)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_latest_capture_failure() -> dict:
    ensure_app_dirs()
    if not CAPTURE_FAILURES_DIR.exists():
        return {}
    files = sorted(CAPTURE_FAILURES_DIR.glob("*.json"), reverse=True)
    if not files:
        return {}
    return json.loads(files[0].read_text(encoding="utf-8"))


def save_daily_capture(
    *,
    candidates: list[Candidate],
    selected_tickers: set[str],
    reviewed_tickers: set[str],
    criteria: ScannerCriteria,
    provider: str,
    mode: TradingMode,
    session: CaptureSession,
    market_regime: MarketRegimeSnapshot,
    capture_time: datetime | None = None,
) -> tuple[Path, Path]:
    capture_time = capture_time or now_central()
    created_at = now_central()
    for candidate in candidates:
        candidate.news = filter_news_known_at_capture(candidate.news, capture_time)
        apply_candidate_news_stack(candidate, now=capture_time)
    payload = {
        "schema_version": 2,
        "capture_time": capture_time.isoformat(),
        "capture_date": capture_time.strftime("%Y-%m-%d"),
        "session": session.value,
        "mode": mode.value,
        "provider": provider,
        "scanner": asdict(criteria),
        "scoring": {
            "profile": next((candidate.score_profile for candidate in candidates if candidate.score_profile), ""),
            "regime": market_regime.regime.value,
        },
        "market": {
            "regime": market_regime.regime.value,
            "symbol": market_regime.symbol,
            "close": market_regime.close,
            "sma_50": market_regime.sma_50,
            "sma_200": market_regime.sma_200,
            "reason": market_regime.reason,
        },
        "candidates": [
            {
                **candidate_to_raw_capture_dict(candidate),
                "rank": index,
            }
            for index, candidate in enumerate(sorted(candidates, key=lambda item: item.score, reverse=True), 1)
        ],
    }
    json_path = capture_json_path(capture_time, session)
    report_path_value = capture_report_path(capture_time, session)
    if json_path.exists() or report_path_value.exists():
        existing = json_path if json_path.exists() else report_path_value
        raise RawCaptureAlreadyExistsError(f"Raw capture already exists and will not be overwritten: {existing}")
    write_raw_text_once(json_path, json.dumps(payload, indent=2))
    write_raw_text_once(report_path_value, capture_to_markdown(payload))
    record_raw_capture_integrity(
        json_path=json_path,
        report_path=report_path_value,
        capture_time=capture_time,
        session=session,
        provider=provider,
        scanner=criteria.name,
        created_at=created_at,
    )
    analysis_payload = copy.deepcopy(payload)
    for candidate in analysis_payload["candidates"]:
        candidate["selected"] = candidate["ticker"] in selected_tickers
        candidate["reviewed"] = candidate["ticker"] in reviewed_tickers
    append_analysis_rows(analysis_payload)
    return json_path, report_path_value


def capture_to_markdown(payload: dict) -> str:
    market = payload["market"]
    scanner = payload["scanner"]
    candidates = payload["candidates"]
    lines = [
        f"# Momentum Hunter {payload['session'].title()} Capture - {payload['capture_date']}",
        "",
        f"- Captured: {payload['capture_time']}",
        f"- Mode: {payload['mode']}",
        f"- Provider: {payload['provider']}",
        f"- Scanner: {scanner['name']}",
        f"- Scoring Profile: {payload.get('scoring', {}).get('profile') or 'unknown'}",
        f"- Market Regime: {market['regime'].title()} ({market['symbol']})",
        f"- Regime Reason: {market['reason']}",
        "",
        "| Rank | Ticker | Score | Latest Article | Articles | Range | Freshness Score | Price | Change | Volume | Rel Vol | Sector |",
        "| ---: | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for candidate in candidates:
        rel_volume = f"{candidate['relative_volume']:.2f}x" if candidate["relative_volume"] else "n/a"
        lines.append(
            f"| {candidate['rank']} | {candidate['ticker']} | {candidate['score']} | "
            f"{format_news_age(candidate.get('latest_article_age_hours'))} | "
            f"{candidate.get('article_count', 0)} | "
            f"{candidate.get('news_range', 'unknown')} | "
            f"{candidate.get('freshness_score', 0)} | "
            f"${candidate['price']:,.2f} | {candidate['percent_change']:.1f}% | "
            f"{candidate['volume']:,} | {rel_volume} | {candidate['sector']} |"
        )
    return "\n".join(lines)


def append_analysis_rows(payload: dict) -> None:
    ensure_app_dirs()
    ensure_csv_fieldnames(ANALYSIS_CSV, ANALYSIS_FIELDNAMES)
    exists = ANALYSIS_CSV.exists()
    with ANALYSIS_CSV.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        if not exists:
            writer.writeheader()
        for candidate in payload["candidates"]:
            writer.writerow(analysis_row_from_capture(payload, candidate))


def write_analysis_rows(rows: list[dict], output_path: Path = ANALYSIS_CSV) -> None:
    ensure_app_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in ANALYSIS_FIELDNAMES})


def analysis_row_from_capture(payload: dict, candidate: dict) -> dict:
    market = payload.get("market", {})
    scanner = payload.get("scanner", {})
    scanner_name = scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)
    return {
        "capture_date": payload.get("capture_date", ""),
        "capture_time": payload.get("capture_time", ""),
        "session": payload.get("session", ""),
        "mode": payload.get("mode", ""),
        "provider": payload.get("provider", ""),
        "scanner": scanner_name,
        "market_regime": market.get("regime", ""),
        "market_symbol": market.get("symbol", ""),
        "market_close": market.get("close", ""),
        "market_sma_50": market.get("sma_50", ""),
        "market_sma_200": market.get("sma_200", ""),
        "rank": candidate.get("rank", ""),
        "selected": candidate.get("selected", False),
        "reviewed": candidate.get("reviewed", False),
        "ticker": candidate.get("ticker", ""),
        "company": candidate.get("company", ""),
        "score": candidate.get("score", 0),
        "news_hours_old": candidate.get("news_hours_old", ""),
        "freshness": candidate.get("freshness", "UNKNOWN"),
        "freshness_score": candidate.get("freshness_score", 0),
        "article_count": candidate.get("article_count", 0),
        "valid_timestamp_count": candidate.get("valid_timestamp_count", 0),
        "known_timestamp_count": candidate.get("known_timestamp_count", 0),
        "unknown_timestamp_count": candidate.get("unknown_timestamp_count", 0),
        "future_timestamp_count": candidate.get("future_timestamp_count", 0),
        "excluded_from_scoring_count": candidate.get("excluded_from_scoring_count", 0),
        "latest_article_age_hours": candidate.get("latest_article_age_hours", ""),
        "oldest_article_age_hours": candidate.get("oldest_article_age_hours", ""),
        "news_range": candidate.get("news_range", "unknown"),
        "freshest_headline": candidate.get("freshest_headline", ""),
        "score_profile": candidate.get("score_profile", ""),
        "score_regime": candidate.get("score_regime", ""),
        "score_reasons": format_score_reasons(candidate.get("score_reasons")),
        "price": candidate.get("price", 0),
        "percent_change": candidate.get("percent_change", 0),
        "volume": candidate.get("volume", 0),
        "relative_volume": candidate.get("relative_volume", ""),
        "market_cap": candidate.get("market_cap", ""),
        "sector": candidate.get("sector", ""),
        "industry": candidate.get("industry", ""),
        "user_notes": candidate.get("user_notes", ""),
    }


def format_score_reasons(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value or "")


def ensure_csv_fieldnames(path: Path, fieldnames: list[str]) -> None:
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []
        if existing_fieldnames == fieldnames:
            return
        rows = list(reader)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def save_watchlist_report(candidates: list[Candidate], for_date: datetime | None = None) -> Path:
    path = report_path(for_date)
    value = for_date or now_central()
    lines = [
        f"# Momentum Hunter Watchlist - {value.strftime('%Y-%m-%d')}",
        "",
        "Research only. Confirm thesis, liquidity, risk, and trade plan manually before trading.",
        "",
    ]
    for index, candidate in enumerate(sorted(candidates, key=lambda item: item.score, reverse=True), 1):
        lines.extend(
            [
                f"## {index}. {candidate.ticker} - {candidate.company}",
                "",
                f"- Score: {candidate.score}",
                f"- Latest Article: {format_news_age(candidate.news_stack.latest_article_age_hours)}",
                f"- Articles Found: {candidate.news_stack.article_count}",
                f"- Range: {format_news_range(candidate.news_stack)}",
                f"- Freshest Headline: {candidate.news_stack.freshest_headline or 'n/a'}",
                f"- Freshness Score: {candidate.freshness_score}",
                f"- Price: ${candidate.price:,.2f}",
                f"- Change: {candidate.percent_change:.1f}%",
                f"- Volume: {candidate.volume:,}",
                f"- Relative Volume: {candidate.relative_volume:.2f}x" if candidate.relative_volume else "- Relative Volume: n/a",
                f"- Market Cap: {format_market_cap(candidate.market_cap)}",
                f"- Sector: {candidate.sector}",
                f"- Industry: {candidate.industry}",
                f"- Score Reasons: {', '.join(candidate.score_reasons) or 'None'}",
                "",
                "### Notes",
                candidate.user_notes.strip() or "No notes entered.",
                "",
                "### Headlines",
            ]
        )
        if candidate.news:
            for item in candidate.news[:6]:
                summary = f" - {item.summary}" if item.summary else ""
                lines.append(f"- {item.headline}{summary}")
        else:
            lines.append("- No headlines loaded.")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def save_snapshot_report(
    candidates: list[Candidate],
    *,
    snapshot_time: datetime | None = None,
    label: str = "session",
) -> Path:
    path = snapshot_path(snapshot_time, label)
    value = snapshot_time or now_central()
    lines = [
        f"# Momentum Hunter Snapshot - {value.strftime('%Y-%m-%d %I:%M %p CT')}",
        "",
        f"Snapshot label: {label}",
        "",
        "Research only. This is a point-in-time capture of the current staged picks.",
        "",
    ]
    for index, candidate in enumerate(sorted(candidates, key=lambda item: item.score, reverse=True), 1):
        lines.extend(
            [
                f"## {index}. {candidate.ticker} - {candidate.company}",
                "",
                f"- Score: {candidate.score}",
                f"- Latest Article: {format_news_age(candidate.news_stack.latest_article_age_hours)}",
                f"- Articles Found: {candidate.news_stack.article_count}",
                f"- Range: {format_news_range(candidate.news_stack)}",
                f"- Freshest Headline: {candidate.news_stack.freshest_headline or 'n/a'}",
                f"- Freshness Score: {candidate.freshness_score}",
                f"- Price: ${candidate.price:,.2f}",
                f"- Change: {candidate.percent_change:.1f}%",
                f"- Volume: {candidate.volume:,}",
                f"- Relative Volume: {candidate.relative_volume:.2f}x" if candidate.relative_volume else "- Relative Volume: n/a",
                f"- Market Cap: {format_market_cap(candidate.market_cap)}",
                f"- Sector: {candidate.sector}",
                f"- Industry: {candidate.industry}",
                f"- Score Reasons: {', '.join(candidate.score_reasons) or 'None'}",
                "",
                "### Notes",
                candidate.user_notes.strip() or "No notes entered.",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_watchlist(for_date: datetime | None = None) -> list[Candidate]:
    path = watchlist_path(for_date)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [candidate_from_dict(item) for item in raw]


def load_latest_watchlist() -> list[Candidate]:
    ensure_app_dirs()
    files = sorted(DATA_DIR.glob("watchlist-*.json"), reverse=True)
    if not files:
        return []
    raw = json.loads(files[0].read_text(encoding="utf-8"))
    return [candidate_from_dict(item) for item in raw]


def load_latest_report() -> str:
    ensure_app_dirs()
    files = sorted(DATA_DIR.glob("watchlist-report-*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text(encoding="utf-8")


def list_snapshot_dates() -> list[str]:
    ensure_app_dirs()
    dates = set()
    for path in DATA_DIR.glob("snapshot-*.md"):
        match = re.match(r"snapshot-(\d{4}-\d{2}-\d{2})-\d{4}-.+\.md$", path.name)
        if match:
            dates.add(match.group(1))
    dates = sorted(dates, reverse=True)
    return dates


def load_snapshot_report_for_date(date_text: str) -> str:
    ensure_app_dirs()
    files = sorted(DATA_DIR.glob(f"snapshot-{date_text}-*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text(encoding="utf-8")


def list_capture_dates() -> list[str]:
    ensure_app_dirs()
    if not CAPTURES_DIR.exists():
        return []
    dates = [path.name for path in CAPTURES_DIR.iterdir() if path.is_dir()]
    return sorted(dates, reverse=True)


def list_capture_sessions(date_text: str) -> list[CaptureSession]:
    base = CAPTURES_DIR / date_text
    if not base.exists():
        return []
    sessions: list[CaptureSession] = []
    for session in (CaptureSession.MORNING, CaptureSession.EVENING, CaptureSession.MANUAL):
        if (base / f"{session.value}.json").exists() or (base / f"{session.value}.md").exists():
            sessions.append(session)
    return sessions


def load_capture_report(date_text: str, session: CaptureSession) -> str:
    path = CAPTURES_DIR / date_text / f"{session.value}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_capture_json(date_text: str, session: CaptureSession) -> dict:
    path = CAPTURES_DIR / date_text / f"{session.value}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_to_dict(candidate: Candidate) -> dict:
    payload = asdict(candidate)
    payload["saved_at"] = candidate.saved_at.isoformat() if candidate.saved_at else None
    payload["news_stack"] = news_stack_to_dict(candidate.news_stack)
    payload.update(news_stack_flat_fields(candidate.news_stack))
    payload["news"] = [
        {
            **asdict(item),
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in candidate.news
    ]
    return payload


def candidate_to_raw_capture_dict(candidate: Candidate) -> dict:
    payload = candidate_to_dict(candidate)
    for field in ("saved_at", "user_notes", "score_reasons"):
        payload.pop(field, None)
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
    news_hours_old = payload.get("news_hours_old")
    if news_hours_old == "":
        news_hours_old = None
    news_stack = news_stack_from_dict(payload.get("news_stack") or payload, news)
    if news_hours_old is None:
        news_hours_old = news_stack.latest_article_age_hours
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
        news_stack=news_stack,
        news_hours_old=news_hours_old,
        freshness=payload.get("freshness", news_stack.freshness),
        freshness_score=payload.get("freshness_score", news_stack.freshness_score),
        score_reasons=payload.get("score_reasons", []),
        score_profile=payload.get("score_profile", ""),
        score_regime=payload.get("score_regime", ""),
        user_notes=payload.get("user_notes", ""),
        saved_at=datetime.fromisoformat(saved_at) if saved_at else None,
    )


def news_stack_to_dict(stack: NewsStack) -> dict:
    payload = asdict(stack)
    payload["latest_article_published_at"] = (
        stack.latest_article_published_at.isoformat() if stack.latest_article_published_at else None
    )
    payload["oldest_article_published_at"] = (
        stack.oldest_article_published_at.isoformat() if stack.oldest_article_published_at else None
    )
    return payload


def news_stack_flat_fields(stack: NewsStack) -> dict:
    return {
        "article_count": stack.article_count,
        "valid_timestamp_count": stack.valid_timestamp_count,
        "known_timestamp_count": stack.known_timestamp_count,
        "unknown_timestamp_count": stack.unknown_timestamp_count,
        "future_timestamp_count": stack.future_timestamp_count,
        "excluded_from_scoring_count": stack.excluded_from_scoring_count,
        "latest_article_age_hours": stack.latest_article_age_hours,
        "oldest_article_age_hours": stack.oldest_article_age_hours,
        "news_range": format_news_range(stack),
        "freshest_headline": stack.freshest_headline,
        "freshest_url": stack.freshest_url,
    }


def news_stack_from_dict(payload: dict, news: list[NewsItem]) -> NewsStack:
    latest_age = optional_float(payload.get("latest_article_age_hours", payload.get("news_hours_old")))
    oldest_age = optional_float(payload.get("oldest_article_age_hours", latest_age))
    article_count = int(payload.get("article_count") or len(news))
    valid_count = int(payload.get("valid_timestamp_count") or payload.get("known_timestamp_count") or (1 if latest_age is not None else 0))
    known_count = int(payload.get("known_timestamp_count") or valid_count)
    unknown_count = int(payload.get("unknown_timestamp_count") or max(0, article_count - known_count))
    future_count = int(payload.get("future_timestamp_count") or 0)
    excluded_count = int(payload.get("excluded_from_scoring_count") or (unknown_count + future_count))
    return NewsStack(
        article_count=article_count,
        valid_timestamp_count=valid_count,
        known_timestamp_count=known_count,
        unknown_timestamp_count=unknown_count,
        future_timestamp_count=future_count,
        excluded_from_scoring_count=excluded_count,
        latest_article_age_hours=latest_age,
        oldest_article_age_hours=oldest_age,
        latest_article_published_at=parse_optional_datetime(payload.get("latest_article_published_at")),
        oldest_article_published_at=parse_optional_datetime(payload.get("oldest_article_published_at")),
        freshest_headline=payload.get("freshest_headline", ""),
        freshest_url=payload.get("freshest_url", ""),
        freshness=payload.get("freshness", "UNKNOWN"),
        freshness_score=int(payload.get("freshness_score") or 0),
    )


def parse_optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_market_cap(value: int) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.1f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return "n/a"
