from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.schwab_overnight_probe import (
    SYMBOLS,
    SchwabOvernightProbeError,
    analyze_candle_rows,
    build_quote_evidence,
    classify_overnight,
    compare_stream_and_history,
    overnight_window,
    write_proof,
)


UTC = timezone.utc


class SchwabOvernightProbeTests(unittest.TestCase):
    def test_sunday_night_and_monday_early_share_one_window(self) -> None:
        sunday = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
        monday = datetime(2026, 8, 10, 6, 0, tzinfo=UTC)
        self.assertEqual(overnight_window(sunday), overnight_window(monday))
        self.assertEqual("OVERNIGHT", classify_overnight(sunday))
        self.assertEqual("OVERNIGHT", classify_overnight(monday))

    def test_friday_night_window_is_unavailable(self) -> None:
        friday_night = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
        start, end = overnight_window(friday_night)
        self.assertEqual(start, end)

    def test_quote_evidence_preserves_three_provider_clocks(self) -> None:
        receipt = datetime(2026, 8, 10, 5, 0, tzinfo=UTC)
        quote = SimpleNamespace(
            provider_quote_timestamp=(receipt - timedelta(seconds=2)).isoformat(),
            provider_bid_timestamp=(receipt - timedelta(seconds=3)).isoformat(),
            provider_ask_timestamp=(receipt - timedelta(seconds=1)).isoformat(),
            source="synthetic",
            bid=1.0,
            ask=1.1,
            last=1.05,
            volume=100,
            realtime=True,
            security_status="Normal",
        )
        result = build_quote_evidence({symbol: quote for symbol in SYMBOLS}, receipt=receipt)
        self.assertEqual(3.0, result["SPY"]["bidAgeSeconds"])
        self.assertEqual(1.0, result["SPY"]["askAgeSeconds"])
        self.assertFalse(result["SPY"]["latestTradeTimestampAvailable"])

    def test_candle_analysis_preserves_sparse_minutes(self) -> None:
        receipt = datetime(2026, 8, 10, 5, 5, tzinfo=UTC)
        rows = [
            {"providerTimestamp": "2026-08-10T05:00:00+00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 4},
            {"providerTimestamp": "2026-08-10T05:02:00+00:00", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 0},
        ]
        result = analyze_candle_rows(rows, receipt=receipt)
        self.assertEqual(1, result["missingMinuteCount"])
        self.assertEqual(1, result["zeroVolumeBarCount"])
        self.assertEqual(3, result["overnightHigh"])
        self.assertTrue(result["ohlcvComplete"])

    def test_candle_analysis_uses_latest_version_once_in_summary(self) -> None:
        receipt = datetime(2026, 8, 10, 5, 2, tzinfo=UTC)
        rows = [
            {"providerTimestamp": "2026-08-10T05:00:00+00:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"providerTimestamp": "2026-08-10T05:00:00+00:00", "open": 1, "high": 3, "low": 1, "close": 3, "volume": 12},
        ]
        result = analyze_candle_rows(rows, receipt=receipt)
        self.assertEqual(1, result["barCount"])
        self.assertEqual(2, result["versionCount"])
        self.assertEqual(1, result["duplicateMinuteCount"])
        self.assertEqual(12, result["cumulativeVolume"])
        self.assertEqual(3, result["overnightHigh"])

    def test_stream_history_comparison_never_blends_sources(self) -> None:
        stream = [{"symbol": "SPY", "providerTimestamp": "x", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]
        history = {"SPY": [{"symbol": "SPY", "providerTimestamp": "x", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 11}]}
        result = compare_stream_and_history(stream, history)
        self.assertEqual(1, result["mismatchCount"])
        self.assertEqual(["volume"], result["mismatches"][0]["fields"])
        self.assertFalse(result["sourcesBlended"])

    def test_write_proof_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proof.json"
            write_proof({"safe": True}, output=path)
            with self.assertRaisesRegex(SchwabOvernightProbeError, "write-once"):
                write_proof({"safe": True}, output=path)

    def test_runtime_surface_has_no_order_or_mutating_http_capability(self) -> None:
        import momentum_hunter.schwab_overnight_probe as module

        source = inspect.getsource(module)
        self.assertNotIn("session.post", source)
        self.assertNotIn("session.put", source)
        self.assertNotIn("session.patch", source)
        self.assertNotIn("session.delete", source)
        self.assertNotIn('"/orders', source)
        self.assertNotIn('"/positions', source)
        self.assertNotIn("FakeBroker", source)


if __name__ == "__main__":
    unittest.main()
