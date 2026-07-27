from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.candle_cutover_inventory import (
    CandleCutoverInventoryError,
    build_candle_cutover_inventory,
    write_cutover_inventory_receipt,
)
from momentum_hunter.schwab_candle_staging import (
    load_monitor_target_selection,
    stage_candidate_candles,
)
from momentum_hunter.schwab_price_history import (
    SchwabPriceBar,
    SchwabPriceHistoryResult,
)
from momentum_hunter.staged_schwab_charts import StagedSchwabChartPaths


OBSERVED_AT = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


class StaticSource:
    def __init__(
        self,
        results: tuple[SchwabPriceHistoryResult, ...],
    ) -> None:
        self.results = results

    def history_batch(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        return self.results


class CandleCutoverInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.minute_path = self.root / "opportunity-minute-bars.json"
        self.daily_path = self.root / "daily-ohlc-bars.json"
        self.database_path = self.root / "momentum-hunter.sqlite3"
        self.target_report = self.root / "opportunity-monitor-targets-current.json"
        self.staged_path = self.root / "staging" / "candles.json"
        self.manifest_path = self.root / "staging" / "candles.manifest.json"
        self.minute_path.write_text(
            json.dumps({"schema_version": 1, "bars": {"CRWV": []}}),
            encoding="utf-8",
        )
        self.daily_path.write_text(
            json.dumps({"schema_version": 1, "records": []}),
            encoding="utf-8",
        )
        self.write_target_report(["SPY", "IWM"])
        self.create_stage(all_results(("SPY", "IWM")))
        self.create_database(legacy_rows=3)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_ready_inventory_names_exact_files_rows_symbols_and_locked_actions(self) -> None:
        paths = self.input_paths()
        before = {path: file_hash(path) for path in paths}

        payload = self.audit()

        after = {path: file_hash(path) for path in paths}
        self.assertEqual(before, after)
        self.assertEqual(
            "READY_FOR_EXPLICIT_DESTRUCTIVE_DECISION",
            payload["status"],
        )
        self.assertTrue(payload["readOnlyAudit"])
        self.assertFalse(payload["deletionPerformed"])
        self.assertFalse(payload["databaseMutationPerformed"])
        self.assertFalse(payload["activeChartSourceChanged"])
        self.assertFalse(payload["cutoverPermitted"])
        self.assertTrue(payload["decisionRequiredImmediatelyBeforeCutover"])
        self.assertEqual(3, payload["sqlite"]["totalRows"])
        self.assertEqual(3, payload["sqlite"]["legacyRows"])
        self.assertEqual(0, payload["sqlite"]["otherRows"])
        self.assertEqual(
            [{"symbol": "CRWV", "rowCount": 3}],
            payload["sqlite"]["legacySymbols"],
        )
        scope = payload["exactCutoverScope"]
        self.assertEqual(2, len(scope["filesToRetireFromActiveUse"]))
        self.assertEqual(3, scope["sqliteRowsToRemove"]["rowCount"])
        self.assertEqual([], scope["actionsPerformed"])
        self.assertTrue(all(item["passed"] for item in payload["requirements"]))

    def test_unexpected_sqlite_rows_and_aliases_block_readiness(self) -> None:
        minute_hash = file_hash(self.minute_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            insert_bar(
                connection,
                symbol="OTHER",
                timestamp="2026-07-27T15:10:00Z",
                source_path=str(self.root / "other.json"),
                source_hash="A" * 64,
            )
            insert_bar(
                connection,
                symbol="ALIAS",
                timestamp="2026-07-27T15:11:00Z",
                source_path=str(self.minute_path),
                source_hash="B" * 64,
            )
            insert_bar(
                connection,
                symbol="HASH",
                timestamp="2026-07-27T15:12:00Z",
                source_path=str(self.root / "renamed.json"),
                source_hash=minute_hash,
            )
            connection.commit()

        payload = self.audit()

        self.assertEqual("NOT_READY", payload["status"])
        self.assertEqual(3, payload["sqlite"]["legacyRows"])
        self.assertEqual(3, payload["sqlite"]["otherRows"])
        self.assertEqual(1, payload["sqlite"]["samePathOtherHashRows"])
        self.assertEqual(1, payload["sqlite"]["sameHashOtherPathRows"])

    def test_truncated_or_partial_replacement_blocks_readiness(self) -> None:
        self.write_target_report(["SPY", "IWM", "QQQ"])
        selection = load_monitor_target_selection(self.target_report, limit=2)
        stage_candidate_candles(
            selection,
            source=StaticSource(all_results(("SPY", "IWM"))),
            output_path=self.staged_path,
            manifest_path=self.manifest_path,
            observed_at=OBSERVED_AT,
            active_paths=(),
        )

        truncated = self.audit()

        self.assertEqual("NOT_READY", truncated["status"])
        self.assertTrue(truncated["replacement"]["selectionTruncated"])

        self.write_target_report(["SPY", "IWM"])
        partial_results = (
            result("SPY", "1m"),
            result("SPY", "Daily", count=1),
            result("IWM", "1m"),
            result("IWM", "Daily"),
        )
        self.create_stage(partial_results)

        partial = self.audit()

        self.assertEqual("NOT_READY", partial["status"])
        states = {
            item["state"]
            for item in partial["replacement"]["coverage"]
        }
        self.assertIn("INSUFFICIENT_DATA", states)

    def test_missing_legacy_file_is_reported_not_ready_without_mutation(self) -> None:
        self.daily_path.unlink()

        payload = self.audit()

        self.assertEqual("NOT_READY", payload["status"])
        self.assertFalse(payload["legacyFiles"]["daily"]["exists"])
        self.assertFalse(
            next(
                item
                for item in payload["requirements"]
                if item["name"] == "LEGACY_DAILY_ARTIFACT_PRESENT"
            )["passed"]
        )

    def test_sqlite_sidecar_blocks_exact_scope_readiness(self) -> None:
        journal = self.database_path.with_name(
            f"{self.database_path.name}-journal"
        )
        journal.write_bytes(b"not-a-hot-journal")

        with self.assertRaisesRegex(
            CandleCutoverInventoryError,
            "sidecar state exists",
        ):
            self.audit()

    def test_missing_table_or_identity_columns_fail_closed(self) -> None:
        self.database_path.unlink()
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("CREATE TABLE other_table (value TEXT)")
            connection.commit()

        with self.assertRaisesRegex(
            CandleCutoverInventoryError,
            "no minute_bars table",
        ):
            self.audit()

        self.database_path.unlink()
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "CREATE TABLE minute_bars (symbol TEXT, timestamp TEXT)"
            )
            connection.commit()

        with self.assertRaisesRegex(
            CandleCutoverInventoryError,
            "source-identity columns",
        ):
            self.audit()

    def test_receipt_cannot_overwrite_inputs_active_names_or_databases(self) -> None:
        payload = self.audit()
        protected = self.input_paths()
        blocked = (
            self.minute_path,
            self.root / "alternate" / "daily-ohlc-bars.json",
            self.root / "report.sqlite3",
        )
        for target in blocked:
            with self.subTest(target=target):
                with self.assertRaises(CandleCutoverInventoryError):
                    write_cutover_inventory_receipt(
                        payload,
                        target,
                        protected_inputs=protected,
                    )

        receipt = self.root / "reports" / "cutover-inventory.json"
        written = write_cutover_inventory_receipt(
            payload,
            receipt,
            protected_inputs=protected,
        )
        self.assertEqual(receipt.resolve(), written)
        self.assertEqual(
            "READY_FOR_EXPLICIT_DESTRUCTIVE_DECISION",
            json.loads(receipt.read_text(encoding="utf-8"))["status"],
        )

    def test_module_contains_no_destructive_or_active_chart_operation(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "candle_cutover_inventory.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "DELETE FROM",
            "UPDATE minute_bars",
            "INSERT INTO",
            "connect_database(",
            "run_collection_cycle",
            "submit_order",
            "cancel_order",
            "place_order",
        )
        for value in forbidden:
            self.assertNotIn(value, source)
        self.assertIn("?mode=ro", source)
        self.assertIn("PRAGMA query_only = ON", source)

    def audit(self) -> dict:
        return build_candle_cutover_inventory(
            staged_paths=StagedSchwabChartPaths(
                candles_path=self.staged_path,
                manifest_path=self.manifest_path,
            ),
            legacy_minute_path=self.minute_path,
            legacy_daily_path=self.daily_path,
            database_path=self.database_path,
            observed_at=OBSERVED_AT,
        )

    def input_paths(self) -> tuple[Path, ...]:
        return (
            self.minute_path,
            self.daily_path,
            self.database_path,
            self.target_report,
            self.staged_path,
            self.manifest_path,
        )

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

    def create_stage(
        self,
        results: tuple[SchwabPriceHistoryResult, ...],
    ) -> None:
        selection = load_monitor_target_selection(self.target_report)
        stage_candidate_candles(
            selection,
            source=StaticSource(results),
            output_path=self.staged_path,
            manifest_path=self.manifest_path,
            observed_at=OBSERVED_AT,
            active_paths=(),
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
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


if __name__ == "__main__":
    unittest.main()
