from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.schwab_candle_staging import (
    load_monitor_target_selection,
    stage_candidate_candles,
)
from momentum_hunter.schwab_price_history import (
    SchwabPriceBar,
    SchwabPriceHistoryResult,
)
from momentum_hunter.staged_schwab_charts import (
    StagedSchwabChartError,
    StagedSchwabChartPaths,
    StagedSchwabChartService,
    load_staged_schwab_artifact,
)


OBSERVED_AT = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


class StaticSource:
    def __init__(
        self,
        results: tuple[SchwabPriceHistoryResult, ...],
    ) -> None:
        self.results = results
        self.calls = 0

    def history_batch(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[str, ...],
    ) -> tuple[SchwabPriceHistoryResult, ...]:
        self.calls += 1
        return self.results


class StagedSchwabChartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.target_report = self.root / "opportunity-monitor-targets-current.json"
        self.target_report.write_text(
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
        self.candles_path = self.root / "staging" / "candles.json"
        self.manifest_path = self.root / "staging" / "candles.manifest.json"
        self.create_stage(all_results(("SPY", "IWM")))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_verified_stage_maps_one_five_and_daily_snapshots_without_activation(self) -> None:
        service = self.service()

        one = service.snapshot("spy", "1m", observed_at=OBSERVED_AT)
        five = service.snapshot("SPY", "5m", observed_at=OBSERVED_AT)
        daily = service.snapshot("IWM", "Daily", observed_at=OBSERVED_AT)

        self.assertEqual("AVAILABLE", one["state"])
        self.assertEqual(6, len(one["candles"]))
        self.assertEqual(2, len(five["candles"]))
        self.assertEqual(6, len(daily["candles"]))
        self.assertEqual(600, sum(item["volume"] for item in five["candles"]))
        self.assertEqual(100.0, five["candles"][0]["open"])
        self.assertEqual(102.0, five["candles"][0]["high"])
        self.assertEqual(99.0, five["candles"][0]["low"])
        self.assertEqual(101.0, five["candles"][0]["close"])
        for snapshot in (one, five, daily):
            self.assertTrue(snapshot["previewOnly"])
            self.assertFalse(snapshot["activeChartSource"])
            self.assertFalse(snapshot["transmitting"])
            self.assertEqual("UNAVAILABLE", snapshot["orderTransmission"])
            self.assertIn("STAGED PREVIEW ONLY", snapshot["summary"])
            self.assertIn("inactive staging", snapshot["lineage"]["sourceLabel"])

    def test_unselected_symbol_is_unavailable_without_fallback(self) -> None:
        snapshot = self.service().snapshot(
            "QQQ",
            "15m",
            observed_at=OBSERVED_AT,
        )

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], snapshot["candles"])
        self.assertIn("No fallback", snapshot["summary"])
        self.assertFalse(snapshot["activeChartSource"])

    def test_stale_and_insufficient_coverage_remain_honest(self) -> None:
        stale = OBSERVED_AT - timedelta(days=8)
        self.create_stage(
            (
                result("SPY", "1m", latest=stale, count=2),
                result("SPY", "Daily", latest=stale, count=1),
                result("IWM", "1m", latest=stale, count=2),
                result("IWM", "Daily", latest=stale, count=1),
            )
        )

        intraday = self.service().snapshot("SPY", "5m", observed_at=OBSERVED_AT)
        daily = self.service().snapshot("SPY", "Daily", observed_at=OBSERVED_AT)

        self.assertEqual("STALE", intraday["state"])
        self.assertEqual("INSUFFICIENT_DATA", daily["state"])

    def test_stage_hash_target_hash_and_recorded_path_tampering_fail(self) -> None:
        original_stage = self.candles_path.read_bytes()
        self.candles_path.write_bytes(original_stage + b" ")
        with self.assertRaisesRegex(StagedSchwabChartError, "hash"):
            self.load()

        self.candles_path.write_bytes(original_stage)
        self.target_report.write_text('{"changed": true}', encoding="utf-8")
        with self.assertRaisesRegex(StagedSchwabChartError, "source report changed"):
            self.load()

        self.restore_valid_stage()
        manifest = self.read_manifest()
        manifest["stagedArtifact"]["path"] = str(self.root / "different.json")
        self.write_manifest(manifest)
        with self.assertRaisesRegex(StagedSchwabChartError, "path"):
            self.load()

    def test_safety_source_schema_and_activation_tampering_fail(self) -> None:
        cases = [
            ("activeChartSource", True),
            ("transmitting", True),
            ("orderTransmission", "AVAILABLE"),
            ("accountDataIncluded", True),
            ("source", "other-provider"),
            ("schemaVersion", 99),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                self.restore_valid_stage()
                manifest = self.read_manifest()
                manifest[field] = value
                self.write_manifest(manifest)
                with self.assertRaises(StagedSchwabChartError):
                    self.load()

        self.restore_valid_stage()
        manifest = self.read_manifest()
        manifest["activation"]["permitted"] = True
        self.write_manifest(manifest)
        with self.assertRaisesRegex(StagedSchwabChartError, "activation"):
            self.load()

    def test_bar_geometry_identity_clock_and_coverage_tampering_fail(self) -> None:
        mutations = (
            lambda stage, manifest: stage["results"][0]["bars"][0].update(
                {"high": 50}
            ),
            lambda stage, manifest: stage["results"][0]["bars"][0].update(
                {"symbol": "QQQ"}
            ),
            lambda stage, manifest: stage["results"][0]["clockSkewProof"].update(
                {"status": "FAIL"}
            ),
            lambda stage, manifest: manifest["coverage"][0].update(
                {"barCount": 999}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.restore_valid_stage()
                stage = self.read_stage()
                manifest = self.read_manifest()
                mutate(stage, manifest)
                self.write_stage_and_rehash(stage, manifest)
                with self.assertRaises(StagedSchwabChartError):
                    self.load()

    def test_duplicate_missing_and_coverage_summary_mismatches_fail(self) -> None:
        self.restore_valid_stage()
        stage = self.read_stage()
        manifest = self.read_manifest()
        stage["results"].append(stage["results"][0])
        self.write_stage_and_rehash(stage, manifest)
        with self.assertRaisesRegex(StagedSchwabChartError, "identities"):
            self.load()

        self.restore_valid_stage()
        stage = self.read_stage()
        manifest = self.read_manifest()
        stage["results"].pop()
        self.write_stage_and_rehash(stage, manifest)
        with self.assertRaisesRegex(StagedSchwabChartError, "cover"):
            self.load()

        self.restore_valid_stage()
        manifest = self.read_manifest()
        manifest["coverageStatus"] = "PARTIAL"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(StagedSchwabChartError, "summary"):
            self.load()

    def test_loading_and_snapshot_do_not_mutate_any_source_artifact(self) -> None:
        paths = (
            self.target_report,
            self.candles_path,
            self.manifest_path,
        )
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }

        self.load()
        self.service().snapshot("SPY", "15m", observed_at=OBSERVED_AT)

        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        self.assertEqual(before, after)

    def test_module_has_no_provider_account_order_or_active_store_path(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "staged_schwab_charts.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "requests.",
            "BoundSchwabAccessTokenProvider",
            "submit_order",
            "cancel_order",
            "place_order",
            "opportunity-minute-bars.json",
            "daily-ohlc-bars.json",
            "momentum_hunter.scoring",
            "momentum_hunter.readiness",
            "momentum_hunter.trade_planning",
            "momentum_hunter.execution",
        )
        for value in forbidden:
            self.assertNotIn(value, source)

    def service(self) -> StagedSchwabChartService:
        return StagedSchwabChartService(
            paths=StagedSchwabChartPaths(
                candles_path=self.candles_path,
                manifest_path=self.manifest_path,
            )
        )

    def load(self):
        return load_staged_schwab_artifact(
            StagedSchwabChartPaths(
                candles_path=self.candles_path,
                manifest_path=self.manifest_path,
            )
        )

    def create_stage(
        self,
        results: tuple[SchwabPriceHistoryResult, ...],
    ) -> None:
        selection = load_monitor_target_selection(self.target_report)
        stage_candidate_candles(
            selection,
            source=StaticSource(results),
            output_path=self.candles_path,
            manifest_path=self.manifest_path,
            observed_at=OBSERVED_AT,
            active_paths=(),
        )

    def restore_valid_stage(self) -> None:
        self.target_report.write_text(
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
        self.create_stage(all_results(("SPY", "IWM")))

    def read_stage(self) -> dict:
        return json.loads(self.candles_path.read_text(encoding="utf-8"))

    def read_manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_stage_and_rehash(self, stage: dict, manifest: dict) -> None:
        self.candles_path.write_text(
            json.dumps(stage, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest["stagedArtifact"]["sha256"] = hashlib.sha256(
            self.candles_path.read_bytes()
        ).hexdigest().upper()
        self.write_manifest(manifest)


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
    latest: datetime = OBSERVED_AT - timedelta(minutes=1),
    count: int = 6,
) -> SchwabPriceHistoryResult:
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


if __name__ == "__main__":
    unittest.main()
