from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR


SAVED_WATCHLIST_SNAPSHOT_SCHEMA_VERSION = 1
SAVED_WATCHLIST_ROW_LIMIT = 100
DEFAULT_STALE_AFTER = timedelta(hours=36)
WATCHLIST_FILENAME = re.compile(r"^watchlist-(\d{4}-\d{2}-\d{2})\.json$")


@dataclass(frozen=True)
class SavedWatchlistPaths:
    data_dir: Path = DATA_DIR


class WorkstationSavedWatchlistService:
    """Read-only, cached projection of the latest persisted watchlist."""

    def __init__(
        self,
        paths: SavedWatchlistPaths | None = None,
        *,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> None:
        self.paths = paths or SavedWatchlistPaths()
        self.stale_after = stale_after
        self._lock = threading.RLock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._source_path: Path | None = None
        self._watchlist_date: str | None = None
        self._source_modified_at: datetime | None = None
        self._items: list[dict[str, Any]] | None = None
        self._error = ""

    def snapshot(self, *, observed_at: datetime | None = None) -> dict[str, Any]:
        observed_at = as_utc(observed_at or datetime.now(timezone.utc))
        with self._lock:
            signature = source_signature(self.paths.data_dir)
            if signature != self._signature:
                self._reload(signature)
            return self._build_snapshot(observed_at)

    def _reload(self, signature: tuple[tuple[str, int, int], ...]) -> None:
        paths = watchlist_paths(self.paths.data_dir)
        self._source_path = paths[0] if paths else None
        self._watchlist_date = watchlist_date(self._source_path)
        self._source_modified_at = path_timestamp(self._source_path)
        self._items = None
        self._error = ""

        if self._source_path is not None:
            self._items, self._error = load_watchlist(self._source_path)
        self._signature = signature

    def _build_snapshot(self, observed_at: datetime) -> dict[str, Any]:
        if self._source_path is None:
            return empty_snapshot(
                observed_at,
                "EMPTY | No persisted saved-watchlist JSON file exists. "
                "No current watchlist or candidate status was inferred.",
            )
        if self._items is None:
            return unavailable_snapshot(
                observed_at,
                self._source_path.name,
                self._watchlist_date,
                self._error or "The latest saved-watchlist file is unreadable.",
            )

        valid_rows: list[dict[str, Any]] = []
        missing_symbol_count = 0
        missing_saved_at_count = 0
        symbols: list[str] = []
        source_times: list[datetime] = []
        for rank, item in enumerate(self._items, start=1):
            symbol = normalize_symbol(item.get("ticker"))
            if not symbol:
                missing_symbol_count += 1
                continue
            saved_at = parse_timestamp(item.get("saved_at"))
            if saved_at is None:
                missing_saved_at_count += 1
            else:
                source_times.append(saved_at)
            symbols.append(symbol)
            valid_rows.append(saved_watchlist_row(item, rank, symbol, saved_at))

        duplicate_symbols = sorted(
            symbol for symbol in set(symbols) if symbols.count(symbol) > 1
        )
        as_of = max(source_times) if source_times else self._source_modified_at
        is_stale = as_of is not None and observed_at - as_of > self.stale_after
        warnings = unique_text(
            [
                f"{missing_symbol_count} stored row(s) have no symbol and were omitted."
                if missing_symbol_count
                else "",
                f"{missing_saved_at_count} usable row(s) have no valid saved_at timestamp."
                if missing_saved_at_count
                else "",
                f"Duplicate stored symbols: {', '.join(duplicate_symbols)}."
                if duplicate_symbols
                else "",
                "The latest saved watchlist is older than the 36-hour display threshold."
                if is_stale
                else "",
            ]
        )

        if not self._items:
            state = "EMPTY"
            summary = (
                f"EMPTY | {self._source_path.name} contains no saved candidates. "
                "No current watchlist or review status was inferred."
            )
        elif not valid_rows:
            state = "UNAVAILABLE"
            summary = (
                f"UNAVAILABLE | {self._source_path.name} contains no usable symbol rows. "
                "No candidate identity was inferred."
            )
        elif missing_symbol_count or missing_saved_at_count or duplicate_symbols:
            state = "PARTIAL"
            summary = (
                f"PARTIAL | {self._source_path.name} contains {len(self._items)} stored row(s), "
                f"of which {len(valid_rows)} have usable symbol identity."
            )
        elif is_stale:
            state = "STALE"
            summary = (
                f"STALE | {self._source_path.name} contains {len(valid_rows)} saved candidate(s), "
                "but its newest stored save time is older than 36 hours."
            )
        else:
            state = "AVAILABLE"
            summary = (
                f"AVAILABLE | {self._source_path.name} contains {len(valid_rows)} saved candidate(s)."
            )

        displayed_rows = valid_rows[:SAVED_WATCHLIST_ROW_LIMIT]
        return {
            "schemaVersion": SAVED_WATCHLIST_SNAPSHOT_SCHEMA_VERSION,
            "state": state,
            "observedAt": timestamp_text(observed_at),
            "asOf": timestamp_text(as_of) if as_of is not None else None,
            "watchlistDate": self._watchlist_date,
            "summary": (
                f"{summary} Source order is preserved; detail is limited to the first "
                f"{SAVED_WATCHLIST_ROW_LIMIT} usable rows. Read-only saved evidence only; "
                "no score, review status, entry plan, report, alert, or execution behavior was changed."
            ),
            "sourceLabel": self._source_path.name,
            "totalItemCount": len(self._items),
            "usableItemCount": len(valid_rows),
            "displayedItemCount": len(displayed_rows),
            "warnings": warnings,
            "items": displayed_rows,
        }


def empty_snapshot(observed_at: datetime, summary: str) -> dict[str, Any]:
    return {
        "schemaVersion": SAVED_WATCHLIST_SNAPSHOT_SCHEMA_VERSION,
        "state": "EMPTY",
        "observedAt": timestamp_text(observed_at),
        "asOf": None,
        "watchlistDate": None,
        "summary": summary,
        "sourceLabel": "No saved watchlist file",
        "totalItemCount": 0,
        "usableItemCount": 0,
        "displayedItemCount": 0,
        "warnings": [],
        "items": [],
    }


def unavailable_snapshot(
    observed_at: datetime,
    source_label: str,
    watchlist_date_value: str | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": SAVED_WATCHLIST_SNAPSHOT_SCHEMA_VERSION,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "asOf": None,
        "watchlistDate": watchlist_date_value,
        "summary": (
            f"UNAVAILABLE | {detail} No saved candidate identity or current watchlist state was inferred."
        ),
        "sourceLabel": source_label,
        "totalItemCount": 0,
        "usableItemCount": 0,
        "displayedItemCount": 0,
        "warnings": unique_text([detail]),
        "items": [],
    }


def saved_watchlist_row(
    item: dict[str, Any],
    rank: int,
    symbol: str,
    saved_at: datetime | None,
) -> dict[str, Any]:
    return {
        "sourceRank": rank,
        "symbol": symbol,
        "company": text_value(item.get("company")),
        "score": integer_or_none(item.get("score")),
        "price": number_or_none(item.get("price")),
        "percentChange": number_or_none(item.get("percent_change")),
        "volume": integer_or_none(item.get("volume")),
        "relativeVolume": number_or_none(item.get("relative_volume")),
        "sector": text_value(item.get("sector")),
        "industry": text_value(item.get("industry")),
        "freshness": text_value(item.get("freshness")),
        "savedAt": timestamp_text(saved_at) if saved_at is not None else None,
        "freshestHeadline": text_value(item.get("freshest_headline")),
        "userNotes": text_value(item.get("user_notes")),
    }


def watchlist_paths(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    paths = [
        path
        for path in data_dir.glob("watchlist-*.json")
        if watchlist_date(path) is not None
    ]
    return sorted(paths, key=lambda path: (watchlist_date(path) or "", path.name), reverse=True)


def source_signature(data_dir: Path) -> tuple[tuple[str, int, int], ...]:
    result: list[tuple[str, int, int]] = []
    for path in watchlist_paths(data_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(result)


def load_watchlist(path: Path) -> tuple[list[dict[str, Any]] | None, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{path.name} is unreadable: {type(exc).__name__}."
    if not isinstance(payload, list):
        return None, f"{path.name} must contain a JSON array."
    if any(not isinstance(item, dict) for item in payload):
        return None, f"{path.name} contains a non-object watchlist row."
    return payload, ""


def watchlist_date(path: Path | None) -> str | None:
    if path is None:
        return None
    match = WATCHLIST_FILENAME.fullmatch(path.name)
    if match is None:
        return None
    value = match.group(1)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def path_timestamp(path: Path | None) -> datetime | None:
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


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


def integer_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        return number if float(value) == number else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_timestamp(value: object) -> datetime | None:
    text = text_value(value)
    if not text:
        return None
    try:
        return as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


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
