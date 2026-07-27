from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.schwab_candle_staging import (
    CandidateCandleStagingError,
    MAX_TARGET_REPORT_BYTES,
    latest_monitor_target_report,
    load_monitor_target_selection,
    stage_candidate_candles,
    validate_result_coverage,
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
        results: tuple[SchwabPriceHistoryResult, ...] = (),
        *,
        failure: Exception | None = None,
    ) -> None:
        self.results = results
        self.failure = failure
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def history_batch(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        self.calls.append((tuple(symbols), tuple(intervals)))
        if self.failure is not None:
            raise self.failure
        return self.results


class MutatingSource(RecordingSource):
    def __init__(
        self,
        report_path: Path,
        results: tuple[SchwabPriceHistoryResult, ...],
    ) -> None:
        super().__init__(results)
        self.report_path = report_path

    def history_batch(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        results = super().history_batch(symbols, intervals)
        self.report_path.write_text('{"changed": true}', encoding="utf-8")
        return results


class CandidateCandleSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_latest_report_and_selection_preserve_persisted_order_and_hash(self) -> None:
        older = self.write_report(
            "opportunity-monitor-targets-20260727T090000.json",
            ["OLD"],
        )
        latest = self.write_report(
            "opportunity-monitor-targets-20260727T100000.json",
            ["CRWV", "NVDA", "SPY"],
        )
        older.touch()
        latest.touch()

        selected_path = latest_monitor_target_report(self.root)
        selection = load_monitor_target_selection(selected_path, limit=2)

        self.assertEqual(latest.resolve(), selected_path.resolve())
        self.assertEqual(("CRWV", "NVDA"), selection.symbols)
        self.assertEqual(3, selection.source_target_count)
        self.assertTrue(selection.truncated)
        self.assertEqual(
            hashlib.sha256(latest.read_bytes()).hexdigest().upper(),
            selection.report_sha256,
        )
        self.assertEqual("2026-07-27T15:00:00Z", selection.report_generated_at)

    def test_missing_malformed_empty_duplicate_and_invalid_reports_fail_closed(self) -> None:
        with self.assertRaises(CandidateCandleStagingError):
            latest_monitor_target_report(self.root)

        malformed = self.root / "opportunity-monitor-targets-bad.json"
        malformed.write_text("{bad-json", encoding="utf-8")
        with self.assertRaises(CandidateCandleStagingError):
            load_monitor_target_selection(malformed)

        empty = self.write_report("empty.json", [])
        with self.assertRaises(CandidateCandleStagingError):
            load_monitor_target_selection(empty)

        duplicate = self.write_report("duplicate.json", ["SPY", "SPY"])
        with self.assertRaises(CandidateCandleStagingError):
            load_monitor_target_selection(duplicate)

        invalid = self.write_report("invalid.json", ["../SPY"])
        with self.assertRaises(CandidateCandleStagingError):
            load_monitor_target_selection(invalid)

    def test_limit_is_bounded_before_any_provider_work(self) -> None:
        report = self.write_report("targets.json", ["SPY"])
        for limit in (0, 26):
            with self.assertRaises(CandidateCandleStagingError):
                load_monitor_target_selection(report, limit=limit)

    def test_oversized_target_report_fails_before_json_parsing(self) -> None:
        report = self.root / "oversized-targets.json"
        with report.open("wb") as destination:
            destination.truncate(MAX_TARGET_REPORT_BYTES + 1)

        with self.assertRaisesRegex(
            CandidateCandleStagingError,
            "invalid size",
        ):
            load_monitor_target_selection(report)

    def write_report(self, name: str, symbols: list[str]) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": "2026-07-27T10:00:00-05:00",
                    },
                    "targets": [{"symbol": symbol} for symbol in symbols],
                }
            ),
            encoding="utf-8",
        )
        return path


class CandidateCandleStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.report = self.root / "opportunity-monitor-targets-current.json"
        self.report.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": "2026-07-27T09:55:00-05:00",
                    },
                    "targets": [{"symbol": "SPY"}, {"symbol": "IWM"}],
                }
            ),
            encoding="utf-8",
        )
        self.selection = load_monitor_target_selection(self.report)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_stages_exact_target_cross_product_with_hash_bound_inactive_manifest(self) -> None:
        source = RecordingSource(all_results(("SPY", "IWM")))
        output = self.root / "staging" / "candles.json"
        report_before = self.report.read_bytes()

        summary = stage_candidate_candles(
            self.selection,
            source=source,
            output_path=output,
            observed_at=OBSERVED_AT,
        )

        manifest = output.with_name("candles.manifest.json")
        staged_payload = json.loads(output.read_text(encoding="utf-8"))
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            [(("SPY", "IWM"), ("1m", "Daily"))],
            source.calls,
        )
        self.assertEqual("PASS", summary["status"])
        self.assertEqual("COMPLETE", summary["coverageStatus"])
        self.assertFalse(staged_payload["activeChartSource"])
        self.assertFalse(manifest_payload["activeChartSource"])
        self.assertFalse(manifest_payload["activation"]["permitted"])
        self.assertEqual(
            self.selection.report_sha256,
            manifest_payload["selection"]["sourceSha256"],
        )
        self.assertEqual(
            hashlib.sha256(output.read_bytes()).hexdigest().upper(),
            manifest_payload["stagedArtifact"]["sha256"],
        )
        self.assertEqual(report_before, self.report.read_bytes())

    def test_stale_and_empty_results_are_staged_honestly_as_partial(self) -> None:
        stale_time = OBSERVED_AT - timedelta(days=8)
        results = (
            result("SPY", "1m", latest=stale_time, count=2),
            result("SPY", "Daily", latest=stale_time, count=0),
            result("IWM", "1m", latest=stale_time, count=2),
            result("IWM", "Daily", latest=stale_time, count=1),
        )
        output = self.root / "partial.json"

        summary = stage_candidate_candles(
            self.selection,
            source=RecordingSource(results),
            output_path=output,
            observed_at=OBSERVED_AT,
        )

        manifest = json.loads(
            output.with_name("partial.manifest.json").read_text(encoding="utf-8")
        )
        states = {
            (item["symbol"], item["interval"]): item["state"]
            for item in manifest["coverage"]
        }
        self.assertEqual("PARTIAL", summary["coverageStatus"])
        self.assertEqual("STALE", states[("SPY", "1m")])
        self.assertEqual("INSUFFICIENT_DATA", states[("SPY", "Daily")])
        self.assertEqual("INSUFFICIENT_DATA", states[("IWM", "Daily")])

    def test_provider_failure_creates_no_partial_stage_or_manifest(self) -> None:
        output = self.root / "failed.json"
        source = RecordingSource(failure=RuntimeError("provider down"))

        with self.assertRaises(RuntimeError):
            stage_candidate_candles(
                self.selection,
                source=source,
                output_path=output,
                observed_at=OBSERVED_AT,
            )

        self.assertFalse(output.exists())
        self.assertFalse(output.with_name("failed.manifest.json").exists())

    def test_active_or_colliding_output_paths_fail_before_provider_access(self) -> None:
        active = self.root / "opportunity-minute-bars.json"
        alternate_active_name = self.root / "alternate" / "daily-ohlc-bars.json"
        active.write_text("legacy", encoding="utf-8")
        source = RecordingSource(all_results(("SPY", "IWM")))

        with self.assertRaises(CandidateCandleStagingError):
            stage_candidate_candles(
                self.selection,
                source=source,
                output_path=active,
                active_paths=(active,),
            )
        with self.assertRaises(CandidateCandleStagingError):
            stage_candidate_candles(
                self.selection,
                source=source,
                output_path=self.root / "same.json",
                manifest_path=self.root / "same.json",
                active_paths=(active,),
            )
        with self.assertRaises(CandidateCandleStagingError):
            stage_candidate_candles(
                self.selection,
                source=source,
                output_path=alternate_active_name,
                active_paths=(active,),
            )

        self.assertEqual([], source.calls)
        self.assertEqual("legacy", active.read_text(encoding="utf-8"))

    def test_target_report_change_during_fetch_refuses_staging(self) -> None:
        output = self.root / "changed-source.json"
        source = MutatingSource(
            self.report,
            all_results(("SPY", "IWM")),
        )

        with self.assertRaisesRegex(
            CandidateCandleStagingError,
            "changed during candle staging",
        ):
            stage_candidate_candles(
                self.selection,
                source=source,
                output_path=output,
                observed_at=OBSERVED_AT,
            )

        self.assertFalse(output.exists())
        self.assertFalse(
            output.with_name("changed-source.manifest.json").exists()
        )

    def test_identity_duplicate_clock_and_candle_mismatches_fail_without_writes(self) -> None:
        output = self.root / "invalid.json"
        valid = list(all_results(("SPY", "IWM")))
        cases = [
            tuple(valid[:-1]),
            tuple(valid + [valid[0]]),
            tuple([replace_clock(valid[0], "FAIL"), *valid[1:]]),
            tuple([replace_bar_symbol(valid[0], "QQQ"), *valid[1:]]),
        ]
        for items in cases:
            with self.subTest(case=len(items)):
                with self.assertRaises(CandidateCandleStagingError):
                    stage_candidate_candles(
                        self.selection,
                        source=RecordingSource(items),
                        output_path=output,
                        observed_at=OBSERVED_AT,
                    )
                self.assertFalse(output.exists())
                self.assertFalse(
                    output.with_name("invalid.manifest.json").exists()
                )

    def test_result_coverage_refuses_future_or_unordered_candles(self) -> None:
        valid = list(all_results(("SPY", "IWM")))
        future = result(
            "SPY",
            "1m",
            latest=OBSERVED_AT + timedelta(minutes=1),
            count=2,
        )
        with self.assertRaises(CandidateCandleStagingError):
            validate_result_coverage(
                self.selection,
                (future, *valid[1:]),
                observed_at=OBSERVED_AT,
            )

        unordered = replace_bars(valid[0], tuple(reversed(valid[0].bars)))
        with self.assertRaises(CandidateCandleStagingError):
            validate_result_coverage(
                self.selection,
                (unordered, *valid[1:]),
                observed_at=OBSERVED_AT,
            )

    def test_module_exposes_no_order_scoring_readiness_or_trade_planning_path(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "schwab_candle_staging.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "submit_order",
            "cancel_order",
            "place_order",
            "momentum_hunter.scoring",
            "momentum_hunter.readiness",
            "momentum_hunter.trade_planning",
            "momentum_hunter.execution",
        )
        for value in forbidden:
            self.assertNotIn(value, source)


def all_results(symbols: tuple[str, ...]) -> tuple[SchwabPriceHistoryResult, ...]:
    return tuple(
        result(symbol, interval)
        for symbol in symbols
        for interval in ("1m", "Daily")
    )


def result(
    symbol: str,
    interval: str,
    *,
    latest: datetime = OBSERVED_AT - timedelta(minutes=1),
    count: int = 2,
) -> SchwabPriceHistoryResult:
    bars = tuple(
        bar(
            symbol,
            interval,
            latest - timedelta(minutes=count - index - 1),
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


def bar(symbol: str, interval: str, timestamp: datetime) -> SchwabPriceBar:
    return SchwabPriceBar(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp.isoformat().replace("+00:00", "Z"),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1000,
    )


def replace_clock(
    value: SchwabPriceHistoryResult,
    status: str,
) -> SchwabPriceHistoryResult:
    return SchwabPriceHistoryResult(
        symbol=value.symbol,
        interval=value.interval,
        requested_at=value.requested_at,
        received_at=value.received_at,
        previous_close=value.previous_close,
        previous_close_date=value.previous_close_date,
        bars=value.bars,
        clock_skew_proof={"status": status},
    )


def replace_bar_symbol(
    value: SchwabPriceHistoryResult,
    symbol: str,
) -> SchwabPriceHistoryResult:
    first = value.bars[0]
    changed = SchwabPriceBar(
        symbol=symbol,
        interval=first.interval,
        timestamp=first.timestamp,
        open=first.open,
        high=first.high,
        low=first.low,
        close=first.close,
        volume=first.volume,
    )
    return replace_bars(value, (changed, *value.bars[1:]))


def replace_bars(
    value: SchwabPriceHistoryResult,
    bars: tuple[SchwabPriceBar, ...],
) -> SchwabPriceHistoryResult:
    return SchwabPriceHistoryResult(
        symbol=value.symbol,
        interval=value.interval,
        requested_at=value.requested_at,
        received_at=value.received_at,
        previous_close=value.previous_close,
        previous_close_date=value.previous_close_date,
        bars=bars,
        clock_skew_proof=value.clock_skew_proof,
    )


if __name__ == "__main__":
    unittest.main()
