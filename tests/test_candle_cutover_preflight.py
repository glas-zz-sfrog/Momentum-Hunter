from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.candle_cutover_preflight import (
    CandleCutoverPreflightError,
    run_candle_cutover_preflight,
)
from momentum_hunter.schwab_price_history import (
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabPriceBar,
    SchwabPriceHistoryResult,
)


OBSERVED_AT = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


class RecordingSource:
    def __init__(
        self,
        results: tuple[SchwabPriceHistoryResult, ...],
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = results
        self.error = error
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def history_batch(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        self.calls.append((symbols, intervals))
        if self.error is not None:
            raise self.error
        return self.results


class CandleCutoverPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.target_report = (
            self.reports_dir
            / "opportunity-monitor-targets-20260727T100000.json"
        )
        self.minute_path = self.root / "opportunity-minute-bars.json"
        self.daily_path = self.root / "daily-ohlc-bars.json"
        self.database_path = self.root / "momentum-hunter.sqlite3"
        self.staged_path = self.root / "staging" / "candles.json"
        self.manifest_path = self.root / "staging" / "candles.manifest.json"
        self.receipt_path = self.root / "staging" / "preflight.json"
        self.minute_path.write_text(
            json.dumps({"schema_version": 1, "bars": {"CRWV": []}}),
            encoding="utf-8",
        )
        self.daily_path.write_text(
            json.dumps({"schema_version": 1, "records": []}),
            encoding="utf-8",
        )
        self.write_target_report(["SPY", "IWM"])
        self.create_database(legacy_rows=3)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_one_command_binds_fresh_full_target_stage_and_inventory(self) -> None:
        source = RecordingSource(all_results(("SPY", "IWM")))
        protected = self.protected_paths()
        before = {path: file_hash(path) for path in protected}

        payload = self.run_preflight(source)

        self.assertEqual(before, {path: file_hash(path) for path in protected})
        self.assertEqual(
            [(("SPY", "IWM"), ("1m", "Daily"))],
            source.calls,
        )
        self.assertEqual(
            "READY_FOR_EXPLICIT_DESTRUCTIVE_DECISION",
            payload["status"],
        )
        self.assertFalse(payload["activeChartSource"])
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["deletionPerformed"])
        self.assertFalse(payload["databaseMutationPerformed"])
        self.assertFalse(payload["activeChartSourceChanged"])
        self.assertFalse(payload["cutoverPermitted"])
        self.assertEqual(
            payload["staging"]["stagedSha256"],
            payload["inventory"]["replacement"]["stagedSha256"],
        )
        self.assertEqual(
            ["SPY", "IWM"],
            payload["inventory"]["replacement"]["symbols"],
        )
        self.assertEqual(3, payload["inventory"]["sqlite"]["legacyRows"])
        self.assertTrue(self.receipt_path.is_file())
        persisted = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(payload, persisted)

    def test_target_set_over_provider_bound_fails_before_fetch_or_writes(self) -> None:
        self.write_target_report(
            [f"S{index:02d}" for index in range(26)]
        )
        source = RecordingSource(())

        with self.assertRaisesRegex(
            CandleCutoverPreflightError,
            "requires the full persisted target set",
        ):
            self.run_preflight(source)

        self.assertEqual([], source.calls)
        self.assertFalse(self.staged_path.exists())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.receipt_path.exists())

    def test_provider_failure_creates_no_stage_manifest_or_receipt(self) -> None:
        source = RecordingSource((), error=RuntimeError("provider unavailable"))

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            self.run_preflight(source)

        self.assertFalse(self.staged_path.exists())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.receipt_path.exists())

    def test_existing_or_protected_receipt_fails_before_fetch_or_staging(self) -> None:
        source = RecordingSource(all_results(("SPY", "IWM")))
        self.receipt_path.parent.mkdir(parents=True)
        self.receipt_path.write_text("preserved", encoding="utf-8")

        with self.assertRaisesRegex(
            CandleCutoverPreflightError,
            "write-once",
        ):
            self.run_preflight(source)

        self.assertEqual([], source.calls)
        self.assertEqual("preserved", self.receipt_path.read_text(encoding="utf-8"))
        self.assertFalse(self.staged_path.exists())
        self.assertFalse(self.manifest_path.exists())

        self.receipt_path.unlink()
        with self.assertRaisesRegex(
            CandleCutoverPreflightError,
            "cannot overwrite",
        ):
            run_candle_cutover_preflight(
                reports_dir=self.reports_dir,
                source=source,
                staged_candles_path=self.staged_path,
                staged_manifest_path=self.manifest_path,
                receipt_path=self.minute_path,
                legacy_minute_path=self.minute_path,
                legacy_daily_path=self.daily_path,
                database_path=self.database_path,
                observed_at=OBSERVED_AT,
                active_paths=(),
            )

        self.assertEqual([], source.calls)
        self.assertFalse(self.staged_path.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_inventory_failure_preserves_inactive_stage_but_no_receipt(self) -> None:
        source = RecordingSource(all_results(("SPY", "IWM")))
        journal = self.database_path.with_name(
            f"{self.database_path.name}-journal"
        )
        journal.write_bytes(b"unexpected-sidecar")
        before = {
            path: file_hash(path)
            for path in self.protected_paths()
        }

        with self.assertRaisesRegex(RuntimeError, "sidecar state exists"):
            self.run_preflight(source)

        self.assertEqual(
            before,
            {path: file_hash(path) for path in self.protected_paths()},
        )
        self.assertTrue(self.staged_path.is_file())
        self.assertTrue(self.manifest_path.is_file())
        self.assertFalse(self.receipt_path.exists())
        staged = json.loads(self.staged_path.read_text(encoding="utf-8"))
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(staged["activeChartSource"])
        self.assertFalse(manifest["activation"]["permitted"])

    def test_unexpected_database_rows_emit_not_ready_receipt_without_mutation(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            insert_bar(
                connection,
                symbol="OTHER",
                timestamp="2026-07-27T15:10:00Z",
                source_path=str(self.root / "other.json"),
                source_hash="A" * 64,
            )
            connection.commit()
        source = RecordingSource(all_results(("SPY", "IWM")))
        database_before = file_hash(self.database_path)

        payload = self.run_preflight(source)

        self.assertEqual("NOT_READY", payload["status"])
        self.assertEqual(1, payload["inventory"]["sqlite"]["otherRows"])
        self.assertFalse(payload["cutoverPermitted"])
        self.assertEqual(database_before, file_hash(self.database_path))
        self.assertTrue(self.receipt_path.is_file())

    def test_module_has_no_cutover_order_or_production_activation_operation(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "candle_cutover_preflight.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "DELETE FROM",
            "UPDATE minute_bars",
            "INSERT INTO",
            "submit_order",
            "cancel_order",
            "place_order",
            "run_collection_cycle",
            "activeChartSourceChanged\": True",
            "cutoverPermitted\": True",
        )
        for value in forbidden:
            self.assertNotIn(value, source)

    def run_preflight(self, source: RecordingSource) -> dict:
        return run_candle_cutover_preflight(
            reports_dir=self.reports_dir,
            source=source,
            staged_candles_path=self.staged_path,
            staged_manifest_path=self.manifest_path,
            receipt_path=self.receipt_path,
            legacy_minute_path=self.minute_path,
            legacy_daily_path=self.daily_path,
            database_path=self.database_path,
            observed_at=OBSERVED_AT,
            active_paths=(),
        )

    def protected_paths(self) -> tuple[Path, ...]:
        paths = [
            self.target_report,
            self.minute_path,
            self.daily_path,
            self.database_path,
        ]
        journal = self.database_path.with_name(
            f"{self.database_path.name}-journal"
        )
        if journal.exists():
            paths.append(journal)
        return tuple(paths)

    def write_target_report(self, symbols: list[str]) -> None:
        self.target_report.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": "2026-07-27T09:55:00-05:00",
                    },
                    "targets": [{"symbol": symbol} for symbol in symbols],
                }
            ),
            encoding="utf-8",
        )

    def create_database(self, *, legacy_rows: int) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE minute_bars (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    source_file_path TEXT,
                    source_file_hash TEXT
                )
                """
            )
            for index in range(legacy_rows):
                insert_bar(
                    connection,
                    symbol="CRWV",
                    timestamp=f"2026-07-27T15:{index:02d}:00Z",
                    source_path=str(self.minute_path),
                    source_hash=file_hash(self.minute_path).lower(),
                )
            connection.commit()


def insert_bar(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    timestamp: str,
    source_path: str,
    source_hash: str,
) -> None:
    connection.execute(
        """
        INSERT INTO minute_bars (
            symbol, timestamp, source, source_file_path, source_file_hash
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            symbol,
            timestamp,
            "legacy-test-source",
            source_path,
            source_hash,
        ),
    )


def all_results(
    symbols: tuple[str, ...],
) -> tuple[SchwabPriceHistoryResult, ...]:
    return tuple(
        result(symbol, interval)
        for symbol in symbols
        for interval in ("1m", "Daily")
    )


def result(
    symbol: str,
    interval: str,
    *,
    count: int = 3,
) -> SchwabPriceHistoryResult:
    latest = OBSERVED_AT - timedelta(minutes=1)
    bars = tuple(
        SchwabPriceBar(
            symbol=symbol,
            interval=interval,
            timestamp=(
                latest - timedelta(minutes=count - index - 1)
            ).isoformat().replace("+00:00", "Z"),
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=100,
        )
        for index in range(count)
    )
    return SchwabPriceHistoryResult(
        symbol=symbol,
        interval=interval,
        requested_at="2026-07-27T14:59:58Z",
        received_at="2026-07-27T15:00:00Z",
        previous_close=100.0,
        previous_close_date="2026-07-24T05:00:00Z",
        bars=bars,
        clock_skew_proof={"status": "PASS"},
        source=SCHWAB_PRICE_HISTORY_SOURCE,
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


if __name__ == "__main__":
    unittest.main()
