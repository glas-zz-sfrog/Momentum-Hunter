from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.canonical_candle_evidence import (
    load_canonical_minute_finality_as_of,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore


def at(minute: int, second: int = 0, *, microsecond: int = 0) -> datetime:
    return datetime(
        2026,
        8,
        26,
        10,
        minute,
        second,
        microsecond,
        tzinfo=EASTERN_TZ,
    )


def candle(*, close: float = 100.0) -> SchwabMinuteCandle:
    return SchwabMinuteCandle(
        symbol="AAA",
        timestamp=at(5),
        open=99.9,
        high=max(100.1, close),
        low=min(99.8, close),
        close=close,
        volume=500.0,
        source=SCHWAB_PRICE_HISTORY_SOURCE,
    )


class ContinuousCandleFinalityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SchwabCandleStore(self.root)

    def snapshot(self, cutoff: datetime):
        return load_canonical_minute_finality_as_of(
            cutoff=cutoff,
            store_root=self.root,
            symbols=("AAA",),
        )

    def test_receipt_before_bar_end_never_becomes_completed_by_waiting(self) -> None:
        self.store.append_history((candle(),), received_at=at(5, 59, microsecond=999999))

        first = self.snapshot(at(6))
        later = self.snapshot(at(30))

        self.assertEqual((), first.versions)
        self.assertEqual((), later.versions)
        self.assertEqual(1, later.provisional_version_count)
        self.assertEqual(0, later.completed_version_count)

    def test_receipt_exactly_at_bar_end_is_completed(self) -> None:
        self.store.append_history((candle(),), received_at=at(6))

        snapshot = self.snapshot(at(6))

        self.assertEqual(1, len(snapshot.versions))
        self.assertEqual(
            at(6).astimezone(timezone.utc).isoformat(),
            snapshot.versions[0].first_received_at,
        )
        self.assertEqual(at(6).isoformat(), snapshot.versions[0].original_first_received_at)
        self.assertEqual(0, snapshot.provisional_version_count)
        self.assertEqual(1, snapshot.completed_version_count)

    def test_first_receipt_after_bar_end_is_completed(self) -> None:
        self.store.append_history((candle(),), received_at=at(6, 1))

        snapshot = self.snapshot(at(6, 1))

        self.assertEqual(1, len(snapshot.versions))
        self.assertEqual(0, snapshot.provisional_version_count)
        self.assertEqual(1, snapshot.completed_version_count)

    def test_later_correction_replaces_provisional_version(self) -> None:
        self.store.append_history((candle(close=100.0),), received_at=at(5, 50))
        self.store.append_history((candle(close=100.05),), received_at=at(6, 2))

        snapshot = self.snapshot(at(6, 2))

        self.assertEqual(1, len(snapshot.versions))
        self.assertEqual(100.05, snapshot.versions[0].bar.close)
        self.assertEqual(1, snapshot.provisional_version_count)
        self.assertEqual(1, snapshot.completed_version_count)

    def test_exact_reassertion_does_not_create_a_new_version(self) -> None:
        first = self.store.append_history((candle(),), received_at=at(6))
        duplicate = self.store.append_history(
            (candle(),), received_at=at(6) + timedelta(seconds=30)
        )

        snapshot = self.snapshot(at(7))

        self.assertEqual(1, first.inserted_count)
        self.assertEqual(1, duplicate.duplicate_count)
        self.assertEqual(1, snapshot.observed_version_count)
        self.assertEqual(1, len(snapshot.versions))

    def test_a_b_a_reassertion_returns_to_same_terminal_semantic_identity(self) -> None:
        self.store.append_history((candle(close=100.0),), received_at=at(6))
        first = self.snapshot(at(6))
        self.store.append_history((candle(close=100.05),), received_at=at(6, 10))
        middle = self.snapshot(at(6, 10))
        self.store.append_history((candle(close=100.0),), received_at=at(6, 20))
        final = self.snapshot(at(6, 20))

        self.assertNotEqual(
            first.versions[0].semantic_identity,
            middle.versions[0].semantic_identity,
        )
        self.assertEqual(
            first.versions[0].semantic_identity,
            final.versions[0].semantic_identity,
        )
        self.assertNotEqual(first.versions[0].version_id, final.versions[0].version_id)

    def test_future_version_is_not_visible_before_its_receipt(self) -> None:
        self.store.append_history((candle(),), received_at=at(6, 1))

        before = self.snapshot(at(6))
        after = self.snapshot(at(6, 1))

        self.assertEqual((), before.versions)
        self.assertEqual(1, len(after.versions))


if __name__ == "__main__":
    unittest.main()
