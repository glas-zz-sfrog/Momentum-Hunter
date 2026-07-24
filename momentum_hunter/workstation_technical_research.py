from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.technical_breakouts import (
    TECHNICAL_BREAKOUT_EVENTS_LATEST_JSON,
    TECHNICAL_BREAKOUT_STUDY_LATEST_JSON,
)


TECHNICAL_RESEARCH_SNAPSHOT_SCHEMA_VERSION = 1
TECHNICAL_RESEARCH_ROW_LIMIT = 50
DEFAULT_STALE_AFTER = timedelta(hours=24)


@dataclass(frozen=True)
class TechnicalResearchPaths:
    events_path: Path = TECHNICAL_BREAKOUT_EVENTS_LATEST_JSON
    study_path: Path = TECHNICAL_BREAKOUT_STUDY_LATEST_JSON


class WorkstationTechnicalResearchService:
    """Read-only, cached projection of persisted technical-breakout reports."""

    def __init__(
        self,
        paths: TechnicalResearchPaths | None = None,
        *,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> None:
        self.paths = paths or TechnicalResearchPaths()
        self.stale_after = stale_after
        self._lock = threading.RLock()
        self._signature: tuple[object, object] | None = None
        self._events: list[dict[str, Any]] | None = None
        self._studies: list[dict[str, Any]] | None = None
        self._event_generated_at: datetime | None = None
        self._study_generated_at: datetime | None = None
        self._events_error = ""
        self._study_error = ""
        self._source_warnings: list[str] = []

    def snapshot(
        self,
        symbol: str,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("A non-empty symbol is required for technical research evidence.")
        observed_at = as_utc(observed_at or datetime.now(timezone.utc))

        with self._lock:
            signature = (path_signature(self.paths.events_path), path_signature(self.paths.study_path))
            if signature != self._signature:
                self._reload(signature)
            return self._build_snapshot(normalized_symbol, observed_at)

    def _reload(self, signature: tuple[object, object]) -> None:
        event_payload, events_error = load_report(self.paths.events_path, "events")
        study_payload, study_error = load_report(self.paths.study_path, "studies")

        self._events = list(event_payload["events"]) if event_payload is not None else None
        self._studies = list(study_payload["studies"]) if study_payload is not None else None
        self._event_generated_at = report_timestamp(event_payload)
        self._study_generated_at = report_timestamp(study_payload)
        self._events_error = events_error
        self._study_error = study_error
        self._source_warnings = unique_text(
            [
                *report_warnings(event_payload),
                *report_warnings(study_payload),
            ]
        )
        self._signature = signature

    def _build_snapshot(self, symbol: str, observed_at: datetime) -> dict[str, Any]:
        if self._events is None:
            summary = (
                f"UNAVAILABLE | Stored technical-breakout events cannot be read for {symbol}. "
                f"{self._events_error or 'The event report is unavailable.'} "
                "No research signal or trade conclusion was inferred."
            )
            return unavailable_snapshot(symbol, observed_at, summary, self.paths, [self._events_error])

        symbol_events = [item for item in self._events if normalize_symbol(item.get("symbol")) == symbol]
        symbol_studies = [
            item for item in (self._studies or []) if normalize_symbol(item.get("symbol")) == symbol
        ]
        ordered_events = sorted(symbol_events, key=research_row_sort_key, reverse=True)
        ordered_studies = sorted(symbol_studies, key=research_row_sort_key, reverse=True)
        valid_source_times = [
            value
            for value in (self._event_generated_at, self._study_generated_at)
            if value is not None
        ]
        as_of = min(valid_source_times) if valid_source_times else None
        warnings = unique_text(
            [
                *self._source_warnings,
                self._events_error,
                self._study_error,
                "The event report does not include a valid generated_at timestamp."
                if self._event_generated_at is None
                else "",
                "The study report does not include a valid generated_at timestamp."
                if self._studies is not None and self._study_generated_at is None
                else "",
            ]
        )

        if (
            self._studies is None
            or self._event_generated_at is None
            or self._study_generated_at is None
        ):
            state = "PARTIAL"
            summary = (
                f"PARTIAL | Stored technical research for {symbol} contains "
                f"{len(symbol_events)} event row(s) and {len(symbol_studies)} studied outcome row(s), "
                "but one source or source timestamp is unavailable."
            )
        elif not symbol_events and not symbol_studies:
            state = "EMPTY"
            summary = (
                f"EMPTY | The persisted technical-breakout reports contain no rows for {symbol}. "
                "Absence of stored rows is not evidence that a breakout is absent."
            )
        elif not symbol_events or not symbol_studies:
            state = "PARTIAL"
            summary = (
                f"PARTIAL | Stored technical research for {symbol} contains "
                f"{len(symbol_events)} event row(s) and {len(symbol_studies)} studied outcome row(s), "
                "so the selected-symbol event/outcome evidence chain is incomplete."
            )
        elif as_of is not None and observed_at - as_of > self.stale_after:
            state = "STALE"
            summary = (
                f"STALE | Stored technical research for {symbol} contains "
                f"{len(symbol_events)} event row(s) and {len(symbol_studies)} studied outcome row(s), "
                "but the persisted reports are older than the 24-hour display threshold."
            )
        else:
            state = "AVAILABLE"
            summary = (
                f"AVAILABLE | Stored technical research for {symbol} contains "
                f"{len(symbol_events)} event row(s) and {len(symbol_studies)} studied outcome row(s)."
            )

        return {
            "schemaVersion": TECHNICAL_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            "symbol": symbol,
            "state": state,
            "observedAt": timestamp_text(observed_at),
            "asOf": timestamp_text(as_of) if as_of is not None else None,
            "summary": (
                f"{summary} Counts cover the full reports; detail is limited to the newest "
                f"{TECHNICAL_RESEARCH_ROW_LIMIT} rows per tab. Research evidence only; no score, "
                "readiness, alert, watchlist, plan, or execution behavior was changed."
            ),
            "sourceLabel": (
                f"{self.paths.events_path.name} + {self.paths.study_path.name}"
                if self._studies is not None
                else self.paths.events_path.name
            ),
            "globalEventCount": len(self._events),
            "globalStudyCount": len(self._studies or []),
            "symbolEventCount": len(symbol_events),
            "symbolStudyCount": len(symbol_studies),
            "presentEventCount": count_status(symbol_events, "Breakout present"),
            "failedStudyCount": count_status(symbol_studies, "Breakout failed"),
            "insufficientDataCount": sum(
                1
                for item in [*symbol_events, *symbol_studies]
                if str(item.get("data_sufficiency", "")).strip().lower() != "sufficient"
            ),
            "warnings": warnings[:20],
            "events": [event_row(item) for item in ordered_events[:TECHNICAL_RESEARCH_ROW_LIMIT]],
            "studies": [study_row(item) for item in ordered_studies[:TECHNICAL_RESEARCH_ROW_LIMIT]],
        }


def unavailable_snapshot(
    symbol: str,
    observed_at: datetime,
    summary: str,
    paths: TechnicalResearchPaths,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schemaVersion": TECHNICAL_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "asOf": None,
        "summary": summary,
        "sourceLabel": f"{paths.events_path.name} + {paths.study_path.name}",
        "globalEventCount": 0,
        "globalStudyCount": 0,
        "symbolEventCount": 0,
        "symbolStudyCount": 0,
        "presentEventCount": 0,
        "failedStudyCount": 0,
        "insufficientDataCount": 0,
        "warnings": unique_text(warnings),
        "events": [],
        "studies": [],
    }


def event_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventId": text_value(item.get("event_id")),
        "eventTimestamp": optional_timestamp_text(item.get("event_timestamp")),
        "eventType": text_value(item.get("event_type")),
        "timeframe": text_value(item.get("timeframe")),
        "status": text_value(item.get("status")) or "Insufficient data",
        "qualityFlag": text_value(item.get("quality_flag")) or "UNAVAILABLE",
        "dataSufficiency": text_value(item.get("data_sufficiency")) or "Insufficient data",
        "triggerPrice": number_or_none(item.get("trigger_price")),
        "distanceAboveTriggerPct": number_or_none(item.get("distance_above_trigger_pct")),
        "relativeVolume": number_or_none(item.get("relative_volume")),
        "volumeConfirmed": bool_or_none(item.get("volume_confirmed")),
        "relativeStrengthConfirmed": bool_or_none(item.get("relative_strength_confirmed")),
        "notes": notes_text(item.get("notes"), "No event notes were stored."),
    }


def study_row(item: dict[str, Any]) -> dict[str, Any]:
    returns = item.get("forward_returns_pct")
    returns = returns if isinstance(returns, dict) else {}
    return {
        "eventId": text_value(item.get("event_id")),
        "eventTimestamp": optional_timestamp_text(item.get("event_timestamp")),
        "eventType": text_value(item.get("event_type")),
        "timeframe": text_value(item.get("timeframe")),
        "status": text_value(item.get("status")) or "Insufficient data",
        "dataSufficiency": text_value(item.get("data_sufficiency")) or "Insufficient data",
        "return5mPct": number_or_none(returns.get("5m")),
        "return15mPct": number_or_none(returns.get("15m")),
        "return60mPct": number_or_none(returns.get("60m")),
        "return1dPct": number_or_none(returns.get("1d")),
        "return5dPct": number_or_none(returns.get("5d")),
        "return10dPct": number_or_none(returns.get("10d")),
        "maxFavorableExcursionPct": number_or_none(item.get("max_favorable_excursion_pct")),
        "maxAdverseExcursionPct": number_or_none(item.get("max_adverse_excursion_pct")),
        "heldAboveBreakoutLevel": bool_or_none(item.get("held_above_breakout_level")),
        "failedBackBelowBreakoutLevel": bool_or_none(item.get("failed_back_below_breakout_level")),
        "becameExtended": bool_or_none(item.get("became_extended")),
        "volumeConfirmed": bool_or_none(item.get("volume_confirmed")),
        "notes": notes_text(item.get("notes"), "No study notes were stored."),
    }


def load_report(path: Path, rows_key: str) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, f"{path.name} does not exist."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{path.name} is unreadable: {type(exc).__name__}."
    if not isinstance(payload, dict):
        return None, f"{path.name} must contain a JSON object."
    if payload.get("schema_version") != 1:
        return None, f"{path.name} has an unsupported schema version."
    if payload.get("research_only") is not True:
        return None, f"{path.name} is missing its research-only safety marker."
    rows = payload.get(rows_key)
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        return None, f"{path.name} has an invalid {rows_key} collection."
    return payload, ""


def path_signature(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return str(path), stat.st_mtime_ns, stat.st_size


def report_timestamp(payload: dict[str, Any] | None) -> datetime | None:
    return parse_timestamp(payload.get("generated_at")) if payload is not None else None


def report_warnings(payload: dict[str, Any] | None) -> list[str]:
    if payload is None or not isinstance(payload.get("warnings"), list):
        return []
    return [text for item in payload["warnings"] if (text := text_value(item))]


def research_row_sort_key(item: dict[str, Any]) -> tuple[bool, str, str]:
    timestamp = optional_timestamp_text(item.get("event_timestamp"))
    return timestamp is not None, timestamp or "", text_value(item.get("event_id"))


def count_status(rows: list[dict[str, Any]], expected: str) -> int:
    return sum(1 for item in rows if text_value(item.get("status")).casefold() == expected.casefold())


def notes_text(value: object, fallback: str) -> str:
    if not isinstance(value, list):
        return fallback
    notes = [text for item in value if (text := text_value(item))]
    return "; ".join(notes) if notes else fallback


def normalize_symbol(value: object) -> str:
    return text_value(value).upper()


def text_value(value: object) -> str:
    return str(value or "").strip()


def number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def parse_timestamp(value: object) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        return as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def optional_timestamp_text(value: object) -> str | None:
    timestamp = parse_timestamp(value)
    return timestamp_text(timestamp) if timestamp is not None else None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = text_value(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
