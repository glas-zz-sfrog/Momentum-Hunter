from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.review import CandidateIdentity, ReviewDecision, load_review_decisions, make_capture_id
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH, find_score_breakdown, score_breakdown_identity, score_breakdown_identity_key
from momentum_hunter.storage import CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR, load_capture_integrity_manifest
from momentum_hunter.time_utils import format_central, now_central


RAW_CAPTURE = "raw capture"
SCORE_EXPLANATION = "derived score explanation"
REVIEW_DECISION = "later review decision"
OUTCOME_LABEL = "later outcome label"
SYSTEM_WARNING = "system warning"


@dataclass(frozen=True)
class SourceValue:
    value: object
    source: str


@dataclass
class TimelineRow:
    identity_key: str
    candidate_identity: CandidateIdentity
    score_identity: dict
    capture_path: str
    capture_date: str
    capture_time: datetime | None
    capture_time_text: str
    age_text: str
    session: str
    provider: str
    scanner: str
    mode: str
    ticker: str
    quarantined: bool
    trust_label: str
    fields: dict[str, SourceValue]
    raw_candidate: dict
    capture_payload: dict
    score_breakdown: dict | None = None
    review_decision: ReviewDecision | None = None
    outcome: dict | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplayViewModel:
    banner: str
    read_only: bool
    row: TimelineRow
    raw_capture_fields: dict[str, SourceValue]
    score_breakdown: dict | None
    review_decision: ReviewDecision | None
    outcome: dict | None
    warnings: list[str]


def build_candidate_timeline(
    ticker: str,
    *,
    include_quarantined: bool = False,
    newest_first: bool = False,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
) -> list[TimelineRow]:
    normalized_ticker = ticker.upper()
    review_decisions = load_review_decisions(review_decisions_path)
    outcomes = load_outcome_rows(outcomes_csv)
    rows: list[TimelineRow] = []
    for capture_path, quarantined in capture_sources(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        include_quarantined=include_quarantined,
    ):
        payload = load_capture_payload(capture_path)
        if not payload:
            continue
        for candidate in payload.get("candidates", []):
            if str(candidate.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(
                build_timeline_row(
                    payload,
                    candidate,
                    capture_path=capture_path,
                    quarantined=quarantined,
                    score_breakdowns_path=score_breakdowns_path,
                    review_decisions=review_decisions,
                    outcomes=outcomes,
                )
            )
    mark_duplicate_rows(rows)
    rows.sort(key=lambda row: (row.capture_time or datetime.min, row.session, row.scanner, row.provider), reverse=newest_first)
    return rows


def build_replay_view_model(row: TimelineRow) -> ReplayViewModel:
    return ReplayViewModel(
        banner="Historical Replay - Point-in-Time Snapshot",
        read_only=True,
        row=row,
        raw_capture_fields=row.fields,
        score_breakdown=row.score_breakdown,
        review_decision=row.review_decision,
        outcome=row.outcome,
        warnings=list(row.warnings),
    )


def build_timeline_row(
    capture_payload: dict,
    candidate_payload: dict,
    *,
    capture_path: Path,
    quarantined: bool,
    score_breakdowns_path: Path,
    review_decisions: dict[str, ReviewDecision],
    outcomes: dict[str, dict],
) -> TimelineRow:
    capture_time_raw = capture_payload.get("capture_time", "")
    capture_time = parse_datetime(capture_time_raw)
    capture_date = capture_payload.get("capture_date", capture_time.strftime("%Y-%m-%d") if capture_time else "")
    session = capture_payload.get("session", "")
    provider = capture_payload.get("provider", "")
    scanner = scanner_name(capture_payload)
    mode = capture_payload.get("mode", "")
    ticker = candidate_payload.get("ticker", "")
    candidate_identity = CandidateIdentity(
        capture_id=make_capture_id(capture_date, session, provider, scanner),
        capture_date=capture_date,
        session=session,
        provider=provider,
        scanner=scanner,
        ticker=ticker,
    )
    score_identity = score_breakdown_identity(
        capture_date=capture_date,
        capture_time=capture_time_raw,
        session=session,
        provider=provider,
        scanner=scanner,
        ticker=ticker,
        mode=mode,
    )
    score_breakdown = find_score_breakdown(score_identity, path=score_breakdowns_path)
    review_decision = review_decisions.get(candidate_identity.key)
    outcome = outcomes.get(outcome_key(capture_date, capture_time_raw, session, provider, scanner, ticker))
    warnings: list[str] = []
    if quarantined:
        warnings.append("Quarantined - Not Trusted for Study Use")
    if score_breakdown is None:
        warnings.append("Missing stored score breakdown")
    elif score_breakdown.get("status") in {"legacy", "incomplete"}:
        warnings.append(f"Score breakdown is {score_breakdown.get('status')}")
    if outcome is None:
        warnings.append("Missing later outcome label")

    fields = {
        "price": SourceValue(candidate_payload.get("price", ""), RAW_CAPTURE),
        "percent_change": SourceValue(candidate_payload.get("percent_change", ""), RAW_CAPTURE),
        "volume": SourceValue(candidate_payload.get("volume", ""), RAW_CAPTURE),
        "relative_volume": SourceValue(candidate_payload.get("relative_volume", ""), RAW_CAPTURE),
        "market_cap": SourceValue(candidate_payload.get("market_cap", ""), RAW_CAPTURE),
        "sector": SourceValue(candidate_payload.get("sector", ""), RAW_CAPTURE),
        "industry": SourceValue(candidate_payload.get("industry", ""), RAW_CAPTURE),
        "score": SourceValue(candidate_payload.get("score", ""), RAW_CAPTURE),
        "score_profile": SourceValue(candidate_payload.get("score_profile", capture_payload.get("scoring", {}).get("profile", "")), RAW_CAPTURE),
        "score_regime": SourceValue(candidate_payload.get("score_regime", capture_payload.get("scoring", {}).get("regime", "")), RAW_CAPTURE),
        "review_status": SourceValue(review_decision.review_status.value if review_decision else "unreviewed", REVIEW_DECISION),
        "note_indicator": SourceValue("yes" if review_decision and review_decision.decision_note else "no", REVIEW_DECISION),
        "outcome_status": SourceValue(outcome.get("outcome_status", "missing") if outcome else "missing", OUTCOME_LABEL),
        "next_day_return_pct": SourceValue(outcome.get("next_day_return_pct", "") if outcome else "", OUTCOME_LABEL),
        "five_day_return_pct": SourceValue(outcome.get("five_day_return_pct", "") if outcome else "", OUTCOME_LABEL),
        "max_gain_pct": SourceValue(outcome.get("max_gain_pct", "") if outcome else "", OUTCOME_LABEL),
        "max_drawdown_pct": SourceValue(outcome.get("max_drawdown_pct", "") if outcome else "", OUTCOME_LABEL),
    }
    identity_key = score_breakdown_identity_key(score_identity)
    return TimelineRow(
        identity_key=identity_key,
        candidate_identity=candidate_identity,
        score_identity=score_identity,
        capture_path=capture_path.as_posix(),
        capture_date=capture_date,
        capture_time=capture_time,
        capture_time_text=format_central(capture_time) if capture_time else capture_time_raw,
        age_text=age_text(capture_time),
        session=session,
        provider=provider,
        scanner=scanner,
        mode=mode,
        ticker=ticker,
        quarantined=quarantined,
        trust_label="Quarantined - Not Trusted for Study Use" if quarantined else "Trusted active capture",
        fields=fields,
        raw_candidate=dict(candidate_payload),
        capture_payload=dict(capture_payload),
        score_breakdown=score_breakdown,
        review_decision=review_decision,
        outcome=outcome,
        warnings=warnings,
    )


def capture_sources(
    *,
    captures_dir: Path,
    manifest_path: Path,
    include_quarantined: bool,
) -> list[tuple[Path, bool]]:
    sources = [(path, False) for path in sorted(captures_dir.rglob("*.json"))]
    if not include_quarantined:
        return sources
    manifest = load_capture_integrity_manifest(manifest_path)
    for record in manifest.get("quarantined_records", {}).values():
        if record.get("kind") not in {"raw_capture_json", "raw_capture"}:
            continue
        quarantine_path = record.get("quarantine_path", "")
        if not quarantine_path:
            continue
        path = resolve_data_path(quarantine_path)
        sources.append((path, True))
    return sources


def load_capture_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def load_outcome_rows(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            key = outcome_key(
                row.get("capture_date", ""),
                row.get("capture_time", ""),
                row.get("session", ""),
                row.get("provider", ""),
                row.get("scanner", ""),
                row.get("ticker", ""),
            )
            rows[key] = row
    return rows


def outcome_key(capture_date: str, capture_time: str, session: str, provider: str, scanner: str, ticker: str) -> str:
    return "|".join([capture_date, capture_time, session, provider, scanner, ticker]).upper()


def mark_duplicate_rows(rows: list[TimelineRow]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.identity_key] = counts.get(row.identity_key, 0) + 1
    for row in rows:
        if counts.get(row.identity_key, 0) > 1:
            row.warnings.append("Duplicate replay identity")


def scanner_name(payload: dict) -> str:
    scanner = payload.get("scanner", {})
    return scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def age_text(value: datetime | None) -> str:
    if value is None:
        return "unknown age"
    delta = now_central() - value
    days = delta.days
    if days >= 1:
        return f"{days}d old"
    hours = max(0, int(delta.total_seconds() // 3600))
    return f"{hours}h old"


def resolve_data_path(key: str) -> Path:
    path = Path(key)
    if path.is_absolute():
        return path
    return DATA_DIR / path
