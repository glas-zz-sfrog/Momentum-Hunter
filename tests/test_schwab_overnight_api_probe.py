from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "run_schwab_overnight_api_probe.py"
SPEC = importlib.util.spec_from_file_location("schwab_overnight_api_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class SchwabOvernightApiProbeTests(unittest.TestCase):
    def test_true_overnight_window_spans_20_to_04_eastern(self) -> None:
        observed = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)
        start, end = probe.require_true_overnight(observed)
        self.assertEqual("2026-08-21T00:00:00+00:00", start.isoformat())
        self.assertEqual("2026-08-21T08:00:00+00:00", end.isoformat())

    def test_quote_timeline_rejects_exact_20_et_as_overnight(self) -> None:
        start = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
        rows = [
            {
                "responseTime": "2026-08-21T06:33:00+00:00",
                "newestProviderTimestamp": start.isoformat(),
                "quote": {"bidPrice": 1.0},
                "extended": {},
            }
        ]
        result = probe.classify_quote_timeline(rows, overnight_start=start)
        self.assertEqual("STALE_FROM_AFTER_HOURS", result["classification"])

    def test_history_counts_true_overnight_windows(self) -> None:
        class Candle:
            def __init__(self, timestamp: datetime) -> None:
                self.timestamp = timestamp

        start = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
        rows = [
            Candle(datetime(2026, 8, 21, 0, 30, tzinfo=timezone.utc)),
            Candle(datetime(2026, 8, 21, 5, 30, tzinfo=timezone.utc)),
        ]
        result = probe.history_summary(
            [row.timestamp for row in rows],
            overnight_start=start,
            observed_at=datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc),
        )
        self.assertEqual("OVERNIGHT_HISTORY_PRESENT", result["classification"])
        self.assertEqual(2, result["barsAfter20Et"])
        self.assertEqual(1, result["barsAfterMidnightEt"])

    def test_history_parser_preserves_duplicate_and_corrected_rows(self) -> None:
        start = datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc)
        timestamp = int(datetime(2026, 8, 21, 1, 0, tzinfo=timezone.utc).timestamp() * 1000)
        result = probe.parse_history_evidence(
            {
                "symbol": "SPY",
                "candles": [
                    {"datetime": timestamp, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3},
                    {"datetime": timestamp, "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 4},
                ],
            },
            expected_symbol="SPY",
            overnight_start=start,
            observed_at=datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(2, result["responseRowCount"])
        self.assertEqual(1, result["uniqueMinuteCount"])
        self.assertEqual(1, result["duplicateRowCount"])
        self.assertEqual(1, result["correctedDuplicateMinuteCount"])

    def test_route_inventory_rejects_account_and_alpaca_routes(self) -> None:
        session = probe.RecordingSession(lambda: datetime.now(timezone.utc))
        with self.assertRaisesRegex(probe.ProbeError, "allowlist"):
            session.get("https://api.schwabapi.com/trader/v1/accounts")
        with self.assertRaisesRegex(probe.ProbeError, "allowlist"):
            session.get("https://paper-api.alpaca.markets/v2/account")

    def test_quote_record_preserves_only_sanitized_market_fields(self) -> None:
        timestamp = 1787280001000
        payload = {
            "SPY": {
                "symbol": "SPY",
                "realtime": True,
                "assetMainType": "EQUITY",
                "quote": {
                    "bidPrice": 100.0,
                    "askPrice": 100.1,
                    "quoteTime": timestamp,
                    "unexpected": "retained only in field-name inventory",
                },
                "extended": {"mark": 100.05, "quoteTime": timestamp},
                "accountHash": "forbidden-source-field",
            }
        }
        now = datetime(2026, 8, 21, 1, 0, tzinfo=timezone.utc)
        result = probe.quote_record(payload, "SPY", requested_at=now, received_at=now)
        self.assertNotIn("accountHash", result)
        self.assertNotIn("unexpected", result["quote"])
        self.assertIn("unexpected", result["quote"]["availableFields"])


if __name__ == "__main__":
    unittest.main()
