from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.outcomes import OUTCOMES_CSV, expected_outcome_session_dates
from momentum_hunter.review import CandidateIdentity, ReviewDecision, load_review_decisions, make_capture_id
from momentum_hunter.scheduling import (
    CaptureCalendarStatus,
    CaptureCalendarClassification,
    calendar_label,
    classify_capture,
)
from momentum_hunter.models import SCANNER_PRESETS
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH, find_score_breakdown, score_breakdown_identity, score_breakdown_identity_key
from momentum_hunter.storage import CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR, load_capture_integrity_manifest
from momentum_hunter.time_utils import format_central, now_central


RAW_CAPTURE = "raw capture"
SCORE_EXPLANATION = "derived score explanation"
REVIEW_DECISION = "later review decision"
OUTCOME_LABEL = "later outcome label"
SYSTEM_WARNING = "system warning"
REPLAY_BANNER = "POINT-IN-TIME REPLAY — READ ONLY"


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
    capture_id: str
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
    calendar_classification: CaptureCalendarClassification
    calendar_label: str
    is_ordinary_non_trading_day: bool
    trust_label: str
    candidate_row_id: str
    candidate_fingerprint: str
    outcome_record_id: str
    last_refresh_time_text: str
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
    include_non_trading_day: bool = False,
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
        for candidate_index, candidate in enumerate(payload.get("candidates", [])):
            if str(candidate.get("ticker", "")).upper() != normalized_ticker:
                continue
            row = build_timeline_row(
                payload,
                candidate,
                candidate_index=candidate_index,
                capture_path=capture_path,
                quarantined=quarantined,
                score_breakdowns_path=score_breakdowns_path,
                review_decisions=review_decisions,
                outcomes=outcomes,
            )
            if row.is_ordinary_non_trading_day and not include_non_trading_day:
                continue
            rows.append(row)
    mark_duplicate_rows(rows)
    rows.sort(key=lambda row: (row.capture_time or datetime.min, row.session, row.scanner, row.provider), reverse=newest_first)
    return rows


def build_replay_view_model(row: TimelineRow) -> ReplayViewModel:
    return ReplayViewModel(
        banner=REPLAY_BANNER,
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
    candidate_index: int = 0,
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
    score_breakdown_status = score_breakdown.get("status", "missing") if score_breakdown else "missing"
    score_engine_version = score_breakdown.get("score_engine_version", "") if score_breakdown else ""
    review_decision = review_decisions.get(candidate_identity.key)
    outcome_record_id = outcome_key(capture_date, capture_time_raw, session, provider, scanner, ticker)
    outcome = outcomes.get(outcome_record_id)
    warnings: list[str] = []
    calendar_classification = classify_capture(capture_time_raw, session, capture_date=capture_date)
    calendar_text = calendar_label(calendar_classification)
    is_ordinary_non_trading_day = (
        not calendar_classification.is_study_eligible
        and session != "preopen"
    )
    if quarantined:
        warnings.append("Quarantined - Not Trusted for Study Use")
    if calendar_classification.capture_calendar_status == CaptureCalendarStatus.PREOPEN_GAP_REVIEW_DAY.value:
        warnings.append("Pre-Open Gap Review - separate from ordinary study statistics")
    elif is_ordinary_non_trading_day:
        warnings.append("Non-study capture - hidden by default and excluded from ordinary study statistics")
    if not calendar_classification.is_study_eligible:
        warnings.append("Non-study-eligible capture - excluded from ordinary study statistics")
    if score_breakdown is None:
        warnings.append("Missing stored score breakdown")
    elif score_breakdown.get("status") in {"legacy", "incomplete"}:
        warnings.append(f"Score breakdown is {score_breakdown.get('status')}")
    if outcome is None:
        warnings.append("Missing later outcome label")
    outcome_context = replay_outcome_context(outcome, capture_date)
    relative_volume_value = replay_relative_volume_value(candidate_payload, scanner)
    if relative_volume_value.source == SYSTEM_WARNING:
        warnings.append("Relative volume unavailable in raw capture - displayed as N/A, not 0.0")

    fields = {
        "price": SourceValue(candidate_payload.get("price", ""), RAW_CAPTURE),
        "percent_change": SourceValue(candidate_payload.get("percent_change", ""), RAW_CAPTURE),
        "volume": SourceValue(candidate_payload.get("volume", ""), RAW_CAPTURE),
        "relative_volume": relative_volume_value,
        "market_cap": SourceValue(candidate_payload.get("market_cap", ""), RAW_CAPTURE),
        "sector": SourceValue(candidate_payload.get("sector", ""), RAW_CAPTURE),
        "industry": SourceValue(candidate_payload.get("industry", ""), RAW_CAPTURE),
        "score": SourceValue(candidate_payload.get("score", ""), RAW_CAPTURE),
        "score_profile": SourceValue(candidate_payload.get("score_profile", capture_payload.get("scoring", {}).get("profile", "")), RAW_CAPTURE),
        "score_regime": SourceValue(candidate_payload.get("score_regime", capture_payload.get("scoring", {}).get("regime", "")), RAW_CAPTURE),
        "score_engine_version": SourceValue(score_engine_version, SCORE_EXPLANATION if score_breakdown else SYSTEM_WARNING),
        "score_breakdown_status": SourceValue(score_breakdown_status, SCORE_EXPLANATION if score_breakdown else SYSTEM_WARNING),
        "market_regime": SourceValue(capture_payload.get("market", {}).get("regime", ""), RAW_CAPTURE),
        "capture_calendar_status": SourceValue(calendar_classification.capture_calendar_status, RAW_CAPTURE),
        "is_study_eligible": SourceValue(calendar_classification.is_study_eligible, RAW_CAPTURE),
        "next_market_session_date": SourceValue(calendar_classification.next_market_session_date, RAW_CAPTURE),
        "review_status": SourceValue(review_decision.review_status.value if review_decision else "unreviewed", REVIEW_DECISION),
        "note_indicator": SourceValue("yes" if review_decision and review_decision.decision_note else "no", REVIEW_DECISION),
        "outcome_status": SourceValue(outcome.get("outcome_status", "missing") if outcome else "missing", OUTCOME_LABEL),
        "next_day_return_pct": SourceValue(outcome.get("next_day_return_pct", "") if outcome else "", OUTCOME_LABEL),
        "five_day_return_pct": SourceValue(outcome.get("five_day_return_pct", "") if outcome else "", OUTCOME_LABEL),
        "max_gain_pct": SourceValue(outcome.get("max_gain_pct", "") if outcome else "", OUTCOME_LABEL),
        "max_drawdown_pct": SourceValue(outcome.get("max_drawdown_pct", "") if outcome else "", OUTCOME_LABEL),
        "outcome_start_date": SourceValue(outcome.get("outcome_start_date", "") if outcome else "", OUTCOME_LABEL),
        "outcome_end_date": SourceValue(outcome.get("outcome_end_date", "") if outcome else "", OUTCOME_LABEL),
        "expected_next_day_session_date": SourceValue(outcome_context["expected_next_day_session_date"], OUTCOME_LABEL),
        "expected_five_day_session_date": SourceValue(outcome_context["expected_five_day_session_date"], OUTCOME_LABEL),
        "next_day_outcome_state": SourceValue(outcome_context["next_day_outcome_state"], OUTCOME_LABEL),
        "five_day_outcome_state": SourceValue(outcome_context["five_day_outcome_state"], OUTCOME_LABEL),
        "outcome_reason": SourceValue(outcome_context["outcome_reason"], OUTCOME_LABEL),
        "outcome_calculation_version": SourceValue(outcome_context["outcome_calculation_version"], OUTCOME_LABEL),
    }
    identity_key = score_breakdown_identity_key(score_identity)
    candidate_row_id = f"{capture_date}|{session}|{provider}|{scanner}|row:{candidate_index}|{ticker}".upper()
    return TimelineRow(
        identity_key=identity_key,
        candidate_identity=candidate_identity,
        score_identity=score_identity,
        capture_path=capture_path.as_posix(),
        capture_id=candidate_identity.capture_id,
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
        calendar_classification=calendar_classification,
        calendar_label=calendar_text,
        is_ordinary_non_trading_day=is_ordinary_non_trading_day,
        trust_label=trust_label(quarantined, calendar_classification, score_breakdown_status),
        candidate_row_id=candidate_row_id,
        candidate_fingerprint=signal_candidate_fingerprint(candidate_payload, scanner),
        outcome_record_id=outcome_record_id if outcome else "missing",
        last_refresh_time_text=format_central(now_central()),
        fields=fields,
        raw_candidate=dict(candidate_payload),
        capture_payload=dict(capture_payload),
        score_breakdown=score_breakdown,
        review_decision=review_decision,
        outcome=outcome,
        warnings=warnings,
    )


def replay_relative_volume_value(candidate_payload: dict, scanner: str) -> SourceValue:
    raw_value = candidate_payload.get("relative_volume", None)
    if raw_value is None or str(raw_value).strip().lower() in {"", "n/a", "na", "none"}:
        return SourceValue("N/A (not captured)", SYSTEM_WARNING)
    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError):
        return SourceValue(raw_value, RAW_CAPTURE)
    if numeric_value == 0.0 and scanner in SCANNER_PRESETS:
        return SourceValue("N/A (legacy zero)", SYSTEM_WARNING)
    return SourceValue(raw_value, RAW_CAPTURE)


def replay_outcome_context(outcome: dict | None, capture_date: str) -> dict[str, str]:
    expected_next = ""
    expected_five = ""
    try:
        next_day, five_day = expected_outcome_session_dates(capture_date)
        expected_next = next_day.isoformat()
        expected_five = five_day.isoformat()
    except ValueError:
        pass
    if outcome is None:
        return {
            "expected_next_day_session_date": expected_next,
            "expected_five_day_session_date": expected_five,
            "next_day_outcome_state": "missing",
            "five_day_outcome_state": "missing",
            "outcome_reason": "missing later outcome label",
            "outcome_calculation_version": "",
        }
    next_day_return = str(outcome.get("next_day_return_pct", "")).strip()
    five_day_return = str(outcome.get("five_day_return_pct", "")).strip()
    outcome_status = str(outcome.get("outcome_status", "")).strip()
    expected_next_outcome = outcome.get("expected_next_day_session_date", "") or expected_next
    expected_five_outcome = outcome.get("expected_five_day_session_date", "") or expected_five
    next_day_state = outcome.get("next_day_outcome_state", "") or legacy_outcome_state(
        next_day_return,
        outcome_status,
        expected_next_outcome,
    )
    five_day_state = outcome.get("five_day_outcome_state", "") or legacy_outcome_state(
        five_day_return,
        outcome_status,
        expected_five_outcome,
    )
    return {
        "expected_next_day_session_date": expected_next_outcome,
        "expected_five_day_session_date": expected_five_outcome,
        "next_day_outcome_state": next_day_state,
        "five_day_outcome_state": five_day_state,
        "outcome_reason": outcome.get("outcome_reason", "") or legacy_outcome_reason(
            outcome_status,
            next_day_return,
            five_day_return,
            expected_next_outcome,
            expected_five_outcome,
        ),
        "outcome_calculation_version": outcome.get("outcome_calculation_version", ""),
    }


def legacy_outcome_state(return_value: str, status: str, expected_date: str) -> str:
    if return_value:
        return "complete"
    try:
        expected_day = date.fromisoformat(expected_date)
    except (TypeError, ValueError):
        return status or "missing"
    if now_central().date() <= expected_day:
        return "pending_not_mature"
    if status in {"pending_next_day", "pending_five_day"}:
        return "provider_data_missing"
    return status or "missing"


def legacy_outcome_reason(status: str, next_day_return: str, five_day_return: str, expected_next: str, expected_five: str) -> str:
    if next_day_return and five_day_return:
        return "complete: legacy outcome row has next-day and five-day returns"
    if next_day_return:
        try:
            expected_five_day = date.fromisoformat(expected_five)
        except (TypeError, ValueError):
            expected_five_day = None
        if expected_five_day and now_central().date() > expected_five_day:
            return f"next-day complete for {expected_next}; five-day provider data missing for {expected_five}"
        return f"next-day complete for {expected_next}; five-day pending until {expected_five}"
    if status:
        return f"legacy outcome status: {status}"
    return "missing outcome state"


def trust_label(quarantined: bool, classification: CaptureCalendarClassification, score_breakdown_status: str) -> str:
    if quarantined:
        return "Quarantined - Not Trusted for Study Use"
    if classification.capture_calendar_status == CaptureCalendarStatus.PREOPEN_GAP_REVIEW_DAY.value:
        return "Pre-Open Gap Review"
    if classification.capture_calendar_status == CaptureCalendarStatus.NON_MARKET_DAY.value:
        return "Non-Trading-Day Observation"
    if not classification.is_study_eligible:
        return "Non-Study-Eligible Observation"
    if score_breakdown_status == "legacy":
        return "Legacy Score Breakdown"
    if score_breakdown_status == "incomplete":
        return "Incomplete Score Breakdown"
    return "Trusted active capture"


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
    signal_counts: dict[str, int] = {}
    for row in rows:
        key = signal_fingerprint_key(row)
        signal_counts[key] = signal_counts.get(key, 0) + 1
    for row in rows:
        if counts.get(row.identity_key, 0) > 1:
            row.warnings.append("Duplicate replay identity")
        if signal_counts.get(signal_fingerprint_key(row), 0) > 1:
            row.warnings.append("Repeated signal fingerprint across captures - timestamp distinguishes this row")


def signal_fingerprint_key(row: TimelineRow) -> str:
    keys = ["ticker", "price", "percent_change", "volume", "relative_volume", "score"]
    values = [row.scanner]
    for key in keys:
        value = row.fields.get(key)
        values.append(str(value.value if value else "").strip().upper())
    return "|".join(values)


def signal_candidate_fingerprint(candidate_payload: dict, scanner: str) -> str:
    keys = ["ticker", "price", "percent_change", "volume", "relative_volume", "score"]
    values = [scanner]
    for key in keys:
        values.append(str(candidate_payload.get(key, "")).strip().upper())
    return "|".join(values)


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
