from __future__ import annotations

import copy
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from momentum_hunter.candidate_story_view_model import (
    CandidateStoryPoint,
    CandidateStorySummary,
    build_candidate_story_summary,
)
from momentum_hunter.config import DATA_DIR
from momentum_hunter.replay import TimelineRow, build_candidate_timeline
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


CANDIDATE_STORY_SCHEMA_VERSION = 1
DEFAULT_MAX_DISPLAY_POINTS = 100
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


class CandidateStoryWorkspaceService:
    """Projects the canonical persisted Candidate Story as bounded read-only JSON."""

    def __init__(
        self,
        *,
        data_dir: Path = DATA_DIR,
        max_display_points: int = DEFAULT_MAX_DISPLAY_POINTS,
        timeline_builder: Callable[..., list[TimelineRow]] = build_candidate_timeline,
        now_provider: Callable[[], datetime] = now_central,
    ) -> None:
        if max_display_points < 1:
            raise ValueError("Candidate Story display point limit must be positive.")
        self._data_dir = data_dir
        self._max_display_points = max_display_points
        self._timeline_builder = timeline_builder
        self._now_provider = now_provider
        self._cache: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}
        self._cache_lock = threading.RLock()

    def snapshot(self, symbol: str) -> dict[str, object]:
        normalized_symbol = normalize_candidate_story_symbol(symbol)
        fingerprint = self._source_fingerprint()
        with self._cache_lock:
            cached = self._cache.get(normalized_symbol)
            if cached is not None and cached[0] == fingerprint:
                return copy.deepcopy(cached[1])

        rows = self._timeline_builder(
            normalized_symbol,
            include_quarantined=False,
            include_non_trading_day=False,
            newest_first=False,
            captures_dir=self._data_dir / "captures",
            manifest_path=self._data_dir / "integrity" / "capture_manifest.json",
            score_breakdowns_path=self._data_dir / "score-breakdowns.json",
            review_decisions_path=self._data_dir / "review-decisions.json",
            outcomes_csv=self._data_dir / "analysis-outcomes.csv",
        )
        snapshot = build_candidate_story_snapshot(
            normalized_symbol,
            rows,
            observed_at=self._now_provider(),
            max_display_points=self._max_display_points,
        )
        with self._cache_lock:
            self._cache[normalized_symbol] = (fingerprint, copy.deepcopy(snapshot))
        return snapshot

    def _source_fingerprint(self) -> tuple[object, ...]:
        sources = [
            self._data_dir / "integrity" / "capture_manifest.json",
            self._data_dir / "score-breakdowns.json",
            self._data_dir / "review-decisions.json",
            self._data_dir / "analysis-outcomes.csv",
        ]
        captures_dir = self._data_dir / "captures"
        if captures_dir.exists():
            sources.extend(sorted(captures_dir.rglob("*.json")))
        fingerprint: list[object] = []
        for path in sources:
            try:
                stat = path.stat()
                relative = path.relative_to(self._data_dir).as_posix()
                fingerprint.append((relative, stat.st_mtime_ns, stat.st_size))
            except (OSError, ValueError):
                fingerprint.append((str(path), 0, 0))
        return tuple(fingerprint)


def normalize_candidate_story_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError("Candidate Story requires a valid ticker symbol.")
    return normalized


def build_candidate_story_snapshot(
    symbol: str,
    rows: list[TimelineRow],
    *,
    observed_at: datetime,
    max_display_points: int = DEFAULT_MAX_DISPLAY_POINTS,
) -> dict[str, object]:
    normalized_symbol = normalize_candidate_story_symbol(symbol)
    if max_display_points < 1:
        raise ValueError("Candidate Story display point limit must be positive.")

    ordered_rows = sorted(
        rows,
        key=lambda row: (
            _sortable_capture_time(row.capture_time),
            row.session,
            row.scanner,
            row.provider,
        ),
    )
    summary = build_candidate_story_summary(ordered_rows)
    if not rows:
        return {
            "schemaVersion": CANDIDATE_STORY_SCHEMA_VERSION,
            "symbol": normalized_symbol,
            "state": "EMPTY",
            "observedAt": _iso_timestamp(observed_at),
            "sourceAsOf": None,
            "sourceLabel": "Persisted trusted capture evidence",
            "summary": f"EMPTY | No trusted persisted Candidate Story captures were found for {normalized_symbol}.",
            "company": "",
            "sector": "",
            "industry": "",
            "status": summary.status,
            "statusDetail": summary.status_detail,
            "firstSeenLabel": summary.first_seen_text,
            "latestSeenLabel": summary.latest_seen_text,
            "peakScoreLabel": summary.peak_score_text,
            "firstPrice": None,
            "latestPrice": None,
            "moveSinceFirstPct": None,
            "firstScore": None,
            "latestScore": None,
            "peakScore": None,
            "trustedCaptureCount": 0,
            "totalPointCount": 0,
            "displayedPointCount": 0,
            "points": [],
            "warnings": list(summary.warnings),
            "readOnly": True,
        }

    displayed_points = summary.points[-max_display_points:]
    warnings = _story_warnings(summary, ordered_rows)
    if len(displayed_points) < len(summary.points):
        warnings.append(
            f"Showing the latest {len(displayed_points)} of {len(summary.points)} trusted capture points."
        )
    state = "PARTIAL" if warnings or summary.status == "Insufficient data" else "AVAILABLE"
    source_as_of = ordered_rows[-1].capture_time if ordered_rows else None
    status_summary = (
        f"{state} | {normalized_symbol} has {summary.trusted_capture_count} trusted capture"
        f"{'' if summary.trusted_capture_count == 1 else 's'} and is classified {summary.status}. "
        "This is read-only evidence; no score, readiness, plan, or execution state was changed."
    )
    return {
        "schemaVersion": CANDIDATE_STORY_SCHEMA_VERSION,
        "symbol": normalized_symbol,
        "state": state,
        "observedAt": _iso_timestamp(observed_at),
        "sourceAsOf": _iso_timestamp(source_as_of) if source_as_of else None,
        "sourceLabel": "Persisted trusted raw captures with labeled later annotations",
        "summary": status_summary,
        "company": summary.company,
        "sector": summary.sector,
        "industry": summary.industry,
        "status": summary.status,
        "statusDetail": summary.status_detail,
        "firstSeenLabel": summary.first_seen_text,
        "latestSeenLabel": summary.latest_seen_text,
        "peakScoreLabel": summary.peak_score_text,
        "firstPrice": summary.first_price,
        "latestPrice": summary.latest_price,
        "moveSinceFirstPct": summary.move_since_first_pct,
        "firstScore": summary.first_score,
        "latestScore": summary.latest_score,
        "peakScore": summary.peak_score,
        "trustedCaptureCount": summary.trusted_capture_count,
        "totalPointCount": len(summary.points),
        "displayedPointCount": len(displayed_points),
        "points": [
            _point_payload(point, sequence=index)
            for index, point in enumerate(displayed_points, start=1)
        ],
        "warnings": warnings,
        "readOnly": True,
    }


def _point_payload(point: CandidateStoryPoint, *, sequence: int) -> dict[str, object]:
    row = point.row
    return {
        "sequence": sequence,
        "identityKey": row.identity_key,
        "captureId": row.capture_id,
        "capturedAt": _iso_timestamp(row.capture_time) if row.capture_time else None,
        "capturedAtLabel": row.capture_time_text or row.capture_date or "Capture time unavailable",
        "captureLabel": point.capture_label,
        "session": row.session,
        "sessionMarker": point.session_marker,
        "provider": row.provider,
        "scanner": row.scanner,
        "mode": row.mode,
        "calendarLabel": row.calendar_label,
        "trustLabel": row.trust_label,
        "price": point.price,
        "score": point.score,
        "volume": point.volume,
        "relativeVolume": point.relative_volume,
        "priceChangePreviousPct": point.price_change_previous_pct,
        "priceChangeFirstPct": point.price_change_first_pct,
        "scoreChangePrevious": point.score_change_previous,
        "captureNote": point.note,
        "laterAnnotation": point.later_annotation,
        "captureFactSource": "raw capture",
        "laterAnnotationSource": "later review/outcome annotation",
        "warnings": list(row.warnings),
        "trusted": not row.quarantined,
    }


def _story_warnings(summary: CandidateStorySummary, rows: list[TimelineRow]) -> list[str]:
    warnings: list[str] = []
    for warning in [*summary.warnings, *(warning for row in rows for warning in row.warnings)]:
        if warning and warning not in warnings:
            warnings.append(warning)
    return warnings


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=CENTRAL_TZ)
    return value.isoformat()


def _sortable_capture_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=CENTRAL_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)
