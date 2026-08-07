from __future__ import annotations

import inspect
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter import legacy_candle_cutover
from momentum_hunter.alert_outcome_updater import (
    MinutePriceBar,
    RetiredMinuteBarSourceError,
    save_minute_bars,
    update_alert_store_from_minute_bars,
)
from momentum_hunter.canonical_candle_evidence import load_canonical_minute_bars
from momentum_hunter.data_quality import build_data_quality_report
from momentum_hunter.evidence_health import build_evidence_health_report
from momentum_hunter.legacy_candle_cutover import build_cutover_plan
from momentum_hunter.market_tape_health import MarketTapeHealthReport
from momentum_hunter.opportunity_alerts import OpportunityAlert, load_alerts, save_alerts
from momentum_hunter.schwab_candle_contract import (
    SCHWAB_CHART_EQUITY_SOURCE,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
    SchwabStreamCandleObservation,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.sqlite_store import connect_database, initialize_schema
from momentum_hunter.sqlite_validation import build_sqlite_validation_report
from momentum_hunter.storage import file_sha256
from momentum_hunter.technical_breakouts import build_technical_breakout_reports


UTC = timezone.utc


class LegacyCandleCutoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.legacy = self.root / "opportunity-minute-bars.json"
        self.database = self.root / "momentum-hunter.sqlite3"
        self.minute_store_root = self.root / "schwab-candles-v1"
        self.archive_root = self.root / "archive"
        self._write_allowed_reference()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_reports_ready_without_mutating_any_input(self) -> None:
        self._write_legacy_fixture()
        self._write_sqlite_rows()
        self._write_schwab_bar()
        runs = self.minute_store_root / "runs"
        runs.mkdir()
        (runs / "backfill.json").write_text('{"status":"COMPLETE"}', encoding="utf-8")
        before = self._hashes()

        payload = self._plan()

        self.assertEqual("READY_FOR_DESTRUCTIVE_APPROVAL", payload["status"])
        self.assertTrue(payload["planOnly"])
        self.assertTrue(payload["inputsUnchanged"])
        self.assertEqual(1, payload["sqlite"]["matchingRows"])
        self.assertEqual("HEALTHY", payload["schwabStore"]["status"])
        self.assertEqual([], payload["blockingReferences"])
        self.assertFalse(self.archive_root.exists())
        self.assertEqual(before, self._hashes())
        self.assertFalse(payload["networkCalled"])
        self.assertFalse(payload["accountCalled"])
        self.assertFalse(payload["orderCalled"])
        self.assertFalse(payload["databaseWritten"])

    def test_unclassified_runtime_reference_blocks_cutover(self) -> None:
        self._write_legacy_fixture()
        self._write_sqlite_rows()
        self._write_schwab_bar()
        unknown = self.repo / "momentum_hunter" / "unknown_runtime.py"
        unknown.write_text('PATH = "opportunity-minute-bars.json"\n', encoding="utf-8")

        payload = self._plan()

        self.assertEqual("BLOCKED", payload["status"])
        self.assertIn("UNCLASSIFIED_ACTIVE_LEGACY_REFERENCE", payload["blockers"])
        self.assertEqual("momentum_hunter/unknown_runtime.py", payload["blockingReferences"][0]["path"])

    def test_exact_sqlite_row_mismatch_blocks_cutover(self) -> None:
        self._write_legacy_fixture()
        self._write_schwab_bar()

        payload = self._plan()

        self.assertEqual("BLOCKED", payload["status"])
        self.assertIn("SQLITE_MINUTE_BARS_TABLE_MISSING", payload["blockers"])

    def test_retired_production_path_cannot_be_recreated(self) -> None:
        with patch(
            "momentum_hunter.alert_outcome_updater.OPPORTUNITY_MINUTE_BARS_PATH",
            self.legacy,
        ):
            with self.assertRaises(RetiredMinuteBarSourceError):
                save_minute_bars({"AAA": [legacy_bar()]}, self.legacy)
        self.assertFalse(self.legacy.exists())

    def test_outcome_updater_reads_reconciled_schwab_bars_without_legacy_write(self) -> None:
        alerts = self.root / "alerts.json"
        save_alerts([alert_for("AAA")], alerts)
        store = SchwabCandleStore(self.minute_store_root)
        store.append_history(
            tuple(
                schwab_bar(timestamp, close=close, high=high, low=low)
                for timestamp, close, high, low in (
                    ("2026-08-06T15:05:00+00:00", 10.5, 10.6, 10.1),
                    ("2026-08-06T15:15:00+00:00", 10.8, 10.85, 10.2),
                    ("2026-08-06T15:30:00+00:00", 11.0, 11.2, 9.8),
                    ("2026-08-06T16:00:00+00:00", 11.1, 11.1, 10.9),
                )
            ),
            received_at=datetime(2026, 8, 6, 16, 1, tzinfo=UTC),
        )

        report = update_alert_store_from_minute_bars(
            alerts_path=alerts,
            minute_store_root=self.minute_store_root,
            generated_at=datetime(2026, 8, 6, 16, 2, tzinfo=UTC),
        )

        outcome = load_alerts(alerts)[0].outcome
        self.assertEqual("COMPLETED", outcome.status)
        self.assertEqual(11.0, outcome.sixty_minute_return_pct)
        self.assertEqual("SCHWAB_RECONCILED_MINUTE_STORE_V1", report.bars_source_kind)
        self.assertEqual("", report.bars_saved_path)
        self.assertFalse(report.legacy_cache_written)
        self.assertFalse(self.legacy.exists())

    def test_active_consumers_use_canonical_schwab_evidence_when_legacy_is_absent(self) -> None:
        alerts = self.root / "alerts.json"
        save_alerts([alert_for("AAA")], alerts)
        self._write_schwab_bar()

        health = build_evidence_health_report(
            alerts_path=alerts,
            minute_store_root=self.minute_store_root,
            outcome_status_path=self.root / "missing-outcome-status.json",
            reports_dir=self.root / "reports",
            generated_at=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
        )
        quality = build_data_quality_report(
            ["AAA"],
            market_tape_report=MarketTapeHealthReport(
                generated_at="2026-08-06T16:00:00+00:00",
                symbols=["AAA"],
                attempts=[],
                usable_symbol_count=0,
                missing_symbol_count=1,
                provider_summary={},
                warnings=[],
            ),
            captures_dir=self.root / "missing-captures",
            minute_store_root=self.minute_store_root,
            generated_at=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
        )
        report_paths = build_technical_breakout_reports(
            captures_path=self.root / "missing-captures.csv",
            outcomes_path=self.root / "missing-outcomes.csv",
            alerts_path=self.root / "missing-alerts.json",
            minute_store_root=self.minute_store_root,
            daily_ohlc_path=None,
            output_dir=self.root / "technical-reports",
            generated_at="2026-08-06T16:00:00+00:00",
        )
        technical = json.loads(report_paths["events_json"].read_text(encoding="utf-8"))

        self.assertEqual(str(self.minute_store_root), health.source_minute_bars_path)
        self.assertEqual([], health.missing_minute_bar_alerts)
        self.assertEqual(
            "SCHWAB_RECONCILED_MINUTE_STORE_V1",
            quality.minute_bar_coverage["source_kind"],
        )
        self.assertEqual(1, quality.minute_bar_coverage["symbols_with_bars"])
        self.assertEqual(
            "schwab-reconciled-minute-store-v1",
            technical["source_paths"]["minute_bars_source_kind"],
        )
        self.assertEqual("technical_breakout_research_engine_v2", technical["engine_version"])
        self.assertFalse(self.legacy.exists())

    def test_stream_only_bar_is_not_promoted_to_canonical_consumer_evidence(self) -> None:
        candle = schwab_bar("2026-08-06T15:00:00+00:00", source=SCHWAB_CHART_EQUITY_SOURCE)
        SchwabCandleStore(self.minute_store_root).append_stream(
            (
                SchwabStreamCandleObservation(
                    arrival_index=1,
                    payload_index=0,
                    received_at=datetime(2026, 8, 6, 15, 0, 1, tzinfo=UTC),
                    candle=candle,
                    minute_identity=f"test|AAA|{candle.timestamp.isoformat()}",
                    update_kind="FIRST_OBSERVATION",
                    changed_fields=(),
                    out_of_order=False,
                    sequence_delta_from_previous_arrival=None,
                ),
            )
        )

        self.assertEqual({}, load_canonical_minute_bars(store_root=self.minute_store_root))

    def test_default_sqlite_validation_marks_legacy_mirror_retired(self) -> None:
        self._write_legacy_fixture()
        with closing(connect_database(self.database)) as connection:
            initialize_schema(connection)
            connection.execute(
                """
                INSERT INTO minute_bars(
                    symbol, timestamp, open, high, low, close, volume, source,
                    granularity, source_file_path, source_file_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "AAA",
                    "2026-08-06T10:00:00-05:00",
                    10.0,
                    10.2,
                    9.9,
                    10.1,
                    100,
                    "synthetic_legacy_fixture",
                    "1m",
                    str(self.legacy.resolve(strict=False)),
                    file_sha256(self.legacy),
                ),
            )
            connection.commit()

        payload = build_sqlite_validation_report(
            db_path=self.database,
            data_quality_report=self.root / "missing-data-quality.json",
            alerts_path=self.root / "missing-alerts.json",
            analysis_captures_path=self.root / "missing-analysis.csv",
            evidence_run_source_paths=[],
            system_status_source_paths=[],
        )
        check = next(item for item in payload["checks"] if item["name"] == "minute_bars_legacy_mirror")

        self.assertEqual("PASS", check["status"])
        self.assertEqual(0, check["source_count"])
        self.assertEqual(1, check["sqlite_count"])
        self.assertEqual(
            "INTENTIONALLY_RETIRED",
            payload["source_files"]["minute_bars"]["status"],
        )

    def test_verifier_has_no_provider_broker_or_write_capability(self) -> None:
        source = inspect.getsource(legacy_candle_cutover)
        for forbidden in (
            "import requests",
            "from requests",
            "urllib.request",
            "submit_order",
            "cancel_order",
            "replace_order",
            "access_token",
            "client_secret",
            "write_text(",
            "write_bytes(",
            "unlink(",
            "DELETE FROM",
            "INSERT INTO",
            "UPDATE ",
        ):
            self.assertNotIn(forbidden, source)

    def _write_allowed_reference(self) -> None:
        path = self.repo / "momentum_hunter" / "candle_paths.py"
        path.parent.mkdir(parents=True)
        path.write_text(
            'LEGACY_OPPORTUNITY_MINUTE_BARS_PATH = "opportunity-minute-bars.json"\n',
            encoding="utf-8",
        )

    def _write_legacy_fixture(self) -> None:
        save_minute_bars({"AAA": [legacy_bar()]}, self.legacy)

    def _write_schwab_bar(self) -> None:
        SchwabCandleStore(self.minute_store_root).append_history(
            (schwab_bar("2026-08-06T15:00:00+00:00"),),
            received_at=datetime(2026, 8, 6, 15, 1, tzinfo=UTC),
        )

    def _write_sqlite_rows(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """
                CREATE TABLE minute_bars (
                    source_file_path TEXT NOT NULL,
                    source_file_hash TEXT NOT NULL,
                    symbol TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO minute_bars(source_file_path, source_file_hash, symbol) VALUES (?, ?, ?)",
                (str(self.legacy.resolve(strict=False)), file_sha256(self.legacy), "AAA"),
            )
            connection.commit()
        finally:
            connection.close()

    def _plan(self) -> dict[str, object]:
        return build_cutover_plan(
            repo_root=self.repo,
            legacy_path=self.legacy,
            sqlite_path=self.database,
            minute_store_root=self.minute_store_root,
            archive_root=self.archive_root,
            expected_legacy_sha256=(
                file_sha256(self.legacy) if self.legacy.exists() else "MISSING"
            ),
            expected_legacy_bar_count=1,
            expected_legacy_symbols=("AAA",),
        )

    def _hashes(self) -> tuple[str, str, tuple[tuple[str, str], ...]]:
        partitions = tuple(
            (str(path), file_sha256(path))
            for path in sorted(self.minute_store_root.glob("*/*.json"))
        )
        return (
            file_sha256(self.legacy) if self.legacy.exists() else "",
            file_sha256(self.database) if self.database.exists() else "",
            partitions,
        )


def legacy_bar() -> MinutePriceBar:
    return MinutePriceBar(
        symbol="AAA",
        timestamp="2026-08-06T10:00:00-05:00",
        open=10.0,
        high=10.2,
        low=9.9,
        close=10.1,
        volume=100,
        source="synthetic_legacy_fixture",
    )


def schwab_bar(
    timestamp: str,
    *,
    close: float = 10.1,
    high: float = 10.2,
    low: float = 9.9,
    source: str = SCHWAB_PRICE_HISTORY_SOURCE,
) -> SchwabMinuteCandle:
    return SchwabMinuteCandle(
        symbol="AAA",
        timestamp=datetime.fromisoformat(timestamp),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=100.0,
        source=source,
    )


def alert_for(symbol: str) -> OpportunityAlert:
    return OpportunityAlert(
        alert_id=f"{symbol}-alert",
        symbol=symbol,
        timestamp="2026-08-06T10:00:00-05:00",
        alert_type="STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE",
        current_state="EXECUTION_READY_TRADE",
        previous_state="PLANNING_SCAFFOLD",
        reason="synthetic",
        price=10.0,
        bid=9.99,
        ask=10.01,
        spread_percent=0.1,
        volume=1_000_000,
        premarket_volume=500_000,
        premarket_percent=2.0,
        rvol=1.3,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.0,
        stop=9.5,
        target_1=10.8,
        target_2=11.5,
        news_catalyst="synthetic",
        market_regime="bull",
        event_mode=False,
        source_report="synthetic.json",
    )


if __name__ == "__main__":
    unittest.main()
