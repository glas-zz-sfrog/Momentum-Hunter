from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.overnight_midweek_replication import (
    OvernightReplicationError,
    adjudicate_alpaca,
    adjudicate_schwab,
    build_comparison,
    canonical_json,
    ensure_sanitized,
    require_midweek_overnight,
    write_once,
)


UTC = timezone.utc
SYMBOLS = ("SPY", "QQQ", "NVDA")


def _schwab(*, quote_age: float, stream_age: float, history_count: int) -> dict[str, object]:
    return {
        "symbols": list(SYMBOLS),
        "quotes": {"records": {symbol: {"quoteAgeSeconds": quote_age} for symbol in SYMBOLS}},
        "stream": {
            "subscriptionAcknowledged": True,
            "summary": {
                symbol: {
                    "latestAgeSeconds": stream_age,
                    "ohlcvComplete": True,
                    "cumulativeVolume": 10,
                }
                for symbol in SYMBOLS
            },
        },
        "priceHistory": {symbol: {"barCount": history_count} for symbol in SYMBOLS},
    }


def _alpaca(*, quote_age: float = 2, bar_age: float = 1000, trade_age: float = 900, bars: int = 4) -> dict[str, object]:
    requests = []
    for data_type, age in (("latestQuote", quote_age), ("latestBar", bar_age), ("latestTrade", trade_age)):
        requests.append(
            {
                "feed": "overnight",
                "dataType": data_type,
                "records": {symbol: {"observedAgeSeconds": age} for symbol in SYMBOLS},
            }
        )
    return {
        "requests": requests,
        "historicalBars": {
            symbol: {"barCount": bars, "missingMinuteCount": 2} for symbol in SYMBOLS
        },
    }


class OvernightMidweekReplicationTests(unittest.TestCase):
    def test_midweek_window_accepts_monday_night_and_tuesday_early(self) -> None:
        require_midweek_overnight(datetime(2026, 8, 11, 3, 30, tzinfo=UTC))
        require_midweek_overnight(datetime(2026, 8, 11, 7, 30, tzinfo=UTC))

    def test_midweek_window_rejects_sunday_and_regular_session(self) -> None:
        with self.assertRaises(OvernightReplicationError):
            require_midweek_overnight(datetime(2026, 8, 10, 3, 30, tzinfo=UTC))
        with self.assertRaises(OvernightReplicationError):
            require_midweek_overnight(datetime(2026, 8, 11, 15, 0, tzinfo=UTC))

    def test_schwab_context_proven_requires_all_components(self) -> None:
        result = adjudicate_schwab(_schwab(quote_age=2, stream_age=20, history_count=3))
        self.assertEqual("SCHWAB_MIDWEEK_OVERNIGHT_CONTEXT_PROVEN", result["classification"])

    def test_schwab_gap_requires_stale_quotes_old_stream_and_empty_history(self) -> None:
        result = adjudicate_schwab(_schwab(quote_age=10000, stream_age=10000, history_count=0))
        self.assertEqual("SCHWAB_TRUE_OVERNIGHT_GAP_CONFIRMED", result["classification"])

    def test_schwab_mixed_result_is_partial(self) -> None:
        result = adjudicate_schwab(_schwab(quote_age=2, stream_age=10000, history_count=0))
        self.assertEqual("SCHWAB_MIDWEEK_OVERNIGHT_PARTIAL", result["classification"])

    def test_missing_schwab_proof_is_inconclusive(self) -> None:
        self.assertEqual("REPLICATION_INCONCLUSIVE", adjudicate_schwab(None)["classification"])

    def test_alpaca_prior_pattern_is_replicated(self) -> None:
        result = adjudicate_alpaca(_alpaca(), _alpaca())
        self.assertEqual("ALPACA_OVERNIGHT_BEHAVIOR_REPLICATED", result["classification"])

    def test_alpaca_fresh_history_is_improved(self) -> None:
        result = adjudicate_alpaca(_alpaca(), _alpaca(bar_age=30, trade_age=30))
        self.assertEqual("ALPACA_MIDWEEK_FIDELITY_IMPROVED", result["classification"])

    def test_comparison_never_grants_authority_or_blends_providers(self) -> None:
        result = build_comparison(
            schwab_sunday=_schwab(quote_age=10000, stream_age=10000, history_count=0),
            alpaca_sunday=_alpaca(),
            schwab_midweek=_schwab(quote_age=10000, stream_age=10000, history_count=0),
            alpaca_midweek_start=_alpaca(),
            alpaca_midweek_end=_alpaca(),
            source_identity={"safe": True},
            created_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
        )
        self.assertEqual("SCHWAB_TRUE_OVERNIGHT_GAP_CONFIRMED", result["overallClassification"])
        self.assertFalse(result["safety"]["providersBlended"])
        self.assertTrue(all(value == "NOT_GRANTED" for value in result["authority"].values()))

    def test_comparison_is_deterministic_for_fixed_evidence_and_clock(self) -> None:
        arguments = {
            "schwab_sunday": _schwab(quote_age=10000, stream_age=10000, history_count=0),
            "alpaca_sunday": _alpaca(),
            "schwab_midweek": _schwab(quote_age=2, stream_age=20, history_count=3),
            "alpaca_midweek_start": _alpaca(),
            "alpaca_midweek_end": _alpaca(),
            "source_identity": {"safe": True},
            "created_at": datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
        }
        first = build_comparison(**arguments)
        second = build_comparison(**arguments)
        self.assertEqual(canonical_json(first), canonical_json(second))

    def test_write_once_and_secret_scan_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proof.json"
            write_once(path, canonical_json({"safe": True}))
            with self.assertRaises(OvernightReplicationError):
                write_once(path, b"again")
            unsafe = Path(directory) / "unsafe.txt"
            unsafe.write_text("APCA-API-SECRET-KEY: value", encoding="utf-8")
            with self.assertRaises(OvernightReplicationError):
                ensure_sanitized([unsafe])

    def test_runtime_has_no_order_network_scheduler_or_service_capability(self) -> None:
        import momentum_hunter.overnight_midweek_replication as module

        source = inspect.getsource(module).lower()
        self.assertNotIn("requests.", source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("register-scheduledtask", source)
        self.assertNotIn("restart-service", source)


if __name__ == "__main__":
    unittest.main()
