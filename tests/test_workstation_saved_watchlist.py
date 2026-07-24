from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.workstation_saved_watchlist import (
    SavedWatchlistPaths,
    WorkstationSavedWatchlistService,
)


class WorkstationSavedWatchlistTests(unittest.TestCase):
    def test_available_snapshot_preserves_source_order_and_stored_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(
                root / "watchlist-2026-07-24.json",
                [
                    item("BBB", 72, "2026-07-23T14:10:00Z"),
                    item("AAA", 98, "2026-07-23T14:20:00Z"),
                ],
            )

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual(1, snapshot["schemaVersion"])
            self.assertEqual("AVAILABLE", snapshot["state"])
            self.assertEqual("2026-07-24", snapshot["watchlistDate"])
            self.assertEqual(2, snapshot["totalItemCount"])
            self.assertEqual(2, snapshot["usableItemCount"])
            self.assertEqual(["BBB", "AAA"], [row["symbol"] for row in snapshot["items"]])
            self.assertEqual([1, 2], [row["sourceRank"] for row in snapshot["items"]])
            self.assertEqual(72, snapshot["items"][0]["score"])
            self.assertEqual(25.5, snapshot["items"][0]["price"])
            self.assertEqual("Stored catalyst for BBB", snapshot["items"][0]["freshestHeadline"])
            self.assertIn("no score", snapshot["summary"])

    def test_old_watchlist_is_stale_without_discarding_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(
                root / "watchlist-2026-07-20.json",
                [item("AAA", 91, "2026-07-20T12:00:00Z")],
            )

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("STALE", snapshot["state"])
            self.assertEqual("AAA", snapshot["items"][0]["symbol"])
            self.assertTrue(any("36-hour" in warning for warning in snapshot["warnings"]))

    def test_no_saved_file_is_empty_not_current_watchlist_inference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = service(Path(directory)).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("EMPTY", snapshot["state"])
            self.assertEqual([], snapshot["items"])
            self.assertIn("No current watchlist", snapshot["summary"])

    def test_empty_saved_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(root / "watchlist-2026-07-24.json", [])

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("EMPTY", snapshot["state"])
            self.assertEqual("watchlist-2026-07-24.json", snapshot["sourceLabel"])

    def test_invalid_collection_or_row_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "watchlist-2026-07-24.json"
            path.write_text(json.dumps({"ticker": "AAA"}), encoding="utf-8")
            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))
            self.assertEqual("UNAVAILABLE", snapshot["state"])

            path.write_text(json.dumps([item("AAA", 91), "bad-row"]), encoding="utf-8")
            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertIn("non-object", snapshot["summary"])

    def test_missing_identity_timestamp_and_duplicates_are_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(
                root / "watchlist-2026-07-24.json",
                [
                    item("", 50),
                    item("AAA", 91, ""),
                    item("AAA", 88, "2026-07-23T14:00:00Z"),
                ],
            )

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertEqual(3, snapshot["totalItemCount"])
            self.assertEqual(2, snapshot["usableItemCount"])
            self.assertEqual(["AAA", "AAA"], [row["symbol"] for row in snapshot["items"]])
            self.assertTrue(any("no symbol" in warning for warning in snapshot["warnings"]))
            self.assertTrue(any("Duplicate" in warning for warning in snapshot["warnings"]))

    def test_all_rows_without_symbol_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(root / "watchlist-2026-07-24.json", [item("", 50)])

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertEqual([], snapshot["items"])
            self.assertIn("no usable symbol", snapshot["summary"])

    def test_detail_cap_preserves_full_and_usable_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                item(f"S{index:03d}", index, "2026-07-23T14:00:00Z")
                for index in range(125)
            ]
            write_watchlist(root / "watchlist-2026-07-24.json", rows)

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual(125, snapshot["totalItemCount"])
            self.assertEqual(125, snapshot["usableItemCount"])
            self.assertEqual(100, snapshot["displayedItemCount"])
            self.assertEqual(100, len(snapshot["items"]))
            self.assertEqual("S000", snapshot["items"][0]["symbol"])
            self.assertEqual("S099", snapshot["items"][-1]["symbol"])

    def test_latest_date_file_is_selected_and_report_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_watchlist(
                root / "watchlist-2026-07-20.json",
                [item("OLD", 10, "2026-07-20T10:00:00Z")],
            )
            write_watchlist(
                root / "watchlist-2026-07-24.json",
                [item("NEW", 20, "2026-07-23T14:00:00Z")],
            )
            (root / "watchlist-report-2099-01-01.json").write_text("[]", encoding="utf-8")
            (root / "watchlist-2099-99-99.json").write_text(
                json.dumps([item("INVALID_DATE", 99)]),
                encoding="utf-8",
            )

            snapshot = service(root).snapshot(observed_at=at("2026-07-23T15:00:00Z"))

            self.assertEqual("watchlist-2026-07-24.json", snapshot["sourceLabel"])
            self.assertEqual("NEW", snapshot["items"][0]["symbol"])

    def test_reads_do_not_mutate_source_and_cache_refreshes_for_new_latest_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_path = root / "watchlist-2026-07-23.json"
            write_watchlist(old_path, [item("OLD", 10, "2026-07-23T10:00:00Z")])
            before = sha256(old_path)
            reader = service(root)

            first = reader.snapshot(observed_at=at("2026-07-23T15:00:00Z"))
            second = reader.snapshot(observed_at=at("2026-07-23T15:00:01Z"))

            self.assertEqual("OLD", first["items"][0]["symbol"])
            self.assertEqual("OLD", second["items"][0]["symbol"])
            self.assertEqual(before, sha256(old_path))

            new_path = root / "watchlist-2026-07-24.json"
            write_watchlist(new_path, [item("NEW", 20, "2026-07-23T14:00:00Z")])
            refreshed = reader.snapshot(observed_at=at("2026-07-23T15:00:02Z"))
            self.assertEqual("NEW", refreshed["items"][0]["symbol"])
            self.assertEqual(before, sha256(old_path))


def service(root: Path) -> WorkstationSavedWatchlistService:
    return WorkstationSavedWatchlistService(SavedWatchlistPaths(root))


def write_watchlist(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def item(
    ticker: str,
    score: int,
    saved_at: str = "2026-07-23T14:00:00Z",
) -> dict:
    return {
        "ticker": ticker,
        "company": f"{ticker or 'Unknown'} Company",
        "score": score,
        "price": 25.5,
        "percent_change": 3.25,
        "volume": 1_250_000,
        "relative_volume": 2.5,
        "sector": "Technology",
        "industry": "Software",
        "freshness": "HOT",
        "saved_at": saved_at,
        "freshest_headline": f"Stored catalyst for {ticker or 'unknown'}",
        "user_notes": "Stored operator note.",
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


if __name__ == "__main__":
    unittest.main()
