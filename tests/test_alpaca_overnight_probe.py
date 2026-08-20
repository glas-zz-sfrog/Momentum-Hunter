from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.alpaca_overnight_probe import (
    ALPACA_MARKET_DATA_BASE_URL,
    AlpacaOvernightEndpointError,
    AlpacaOvernightTransport,
    adjudicate_probe,
    analyze_bars,
    classify_latency,
    classify_session,
    compare_bar_observations,
    _parse_latest_payload,
    write_proof,
)
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperCredentials


UTC = timezone.utc


class _Response:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = {"X-Request-ID": "synthetic-request"}
        self.content = json.dumps(payload).encode("utf-8")
        self.is_redirect = False

    def json(self) -> object:
        return self.payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.response


class AlpacaOvernightProbeTests(unittest.TestCase):
    def test_transport_is_exact_host_get_only_and_sanitized(self) -> None:
        session = _Session(_Response({"bars": {}}))
        clock = lambda: datetime(2026, 8, 10, 2, 30, tzinfo=UTC)
        transport = AlpacaOvernightTransport(session=session, clock=clock)
        credentials = AlpacaPaperCredentials("SYNTHETIC-KEY", "SYNTHETIC-SECRET")
        observation, payload = transport.get(
            "/v2/stocks/bars/latest",
            params={"symbols": "SPY,QQQ,NVDA", "feed": "overnight"},
            credentials=credentials,
            feed="overnight",
            data_type="latestBar",
        )
        self.assertEqual({"bars": {}}, payload)
        self.assertEqual("GET", observation["requestMethod"])
        self.assertEqual("data.alpaca.markets", observation["endpointHost"])
        self.assertNotIn(credentials.key_id, json.dumps(observation))
        self.assertNotIn(credentials.secret_key, json.dumps(observation))
        self.assertEqual(f"{ALPACA_MARKET_DATA_BASE_URL}/v2/stocks/bars/latest", session.calls[0][0])
        self.assertNotIn("orders", session.calls[0][0])
        self.assertNotIn("positions", session.calls[0][0])

    def test_transport_rejects_live_trading_and_unknown_paths(self) -> None:
        with self.assertRaises(AlpacaOvernightEndpointError):
            AlpacaOvernightTransport(base_url="https://api.alpaca.markets")
        transport = AlpacaOvernightTransport(session=_Session(_Response({})))
        with self.assertRaises(AlpacaOvernightEndpointError):
            transport.get(
                "/v2/account",
                params={},
                credentials=AlpacaPaperCredentials("KEY", "SECRET"),
                feed="overnight",
                data_type="account",
            )

    def test_transport_allows_only_bounded_per_symbol_history_families(self) -> None:
        session = _Session(_Response({"quotes": []}))
        transport = AlpacaOvernightTransport(session=session)
        credentials = AlpacaPaperCredentials("KEY", "SECRET")
        for suffix in ("bars", "quotes", "trades"):
            transport.get(
                f"/v2/stocks/SPY/{suffix}",
                params={"feed": "overnight"},
                credentials=credentials,
                feed="overnight",
                data_type=f"historical{suffix.title()}",
            )
        self.assertEqual(3, len(session.calls))
        with self.assertRaises(AlpacaOvernightEndpointError):
            transport.get(
                "/v2/stocks/SPY/orders",
                params={},
                credentials=credentials,
                feed="overnight",
                data_type="orders",
            )

    def test_session_classification_covers_sunday_overnight(self) -> None:
        self.assertEqual("OVERNIGHT", classify_session(datetime(2026, 8, 10, 1, 0, tzinfo=UTC)))
        self.assertEqual("PREMARKET", classify_session(datetime(2026, 8, 10, 9, 0, tzinfo=UTC)))
        self.assertEqual("REGULAR", classify_session(datetime(2026, 8, 10, 15, 0, tzinfo=UTC)))

    def test_latency_uses_feed_semantics_without_strategy_threshold(self) -> None:
        timestamp = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
        receipt = timestamp + timedelta(minutes=16)
        self.assertEqual("DELAYED_CONTEXT", classify_latency(timestamp, receipt=receipt, feed="overnight", data_type="latestQuote"))
        self.assertEqual("FRESH_CONTEXT", classify_latency(receipt - timedelta(seconds=2), receipt=receipt, feed="overnight", data_type="latestQuote"))
        self.assertEqual("DELAYED_CONTEXT", classify_latency(timestamp, receipt=receipt, feed="overnight", data_type="latestBar"))
        self.assertEqual("DELAYED_CONTEXT", classify_latency(timestamp, receipt=receipt, feed="boats", data_type="latestBar"))
        self.assertEqual("DELAYED_CONTEXT", classify_latency(timestamp, receipt=receipt, feed="overnight", data_type="latestTrade"))

    def test_snapshot_accepts_alpaca_top_level_symbol_map(self) -> None:
        receipt = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)
        parsed = _parse_latest_payload(
            "snapshot",
            {
                "SPY": {
                    "minuteBar": {"t": "2026-08-10T02:45:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10},
                    "latestQuote": {"t": "2026-08-10T02:59:59Z", "bp": 1, "ap": 2},
                }
            },
            symbols=("SPY",),
            receipt=receipt,
            feed="overnight",
        )
        self.assertEqual(2, parsed["SPY"]["minuteBar"]["close"])
        self.assertEqual("FRESH_CONTEXT", parsed["SPY"]["latestQuote"]["latencyClassification"])

    def test_bar_analysis_preserves_gaps_duplicates_and_volume(self) -> None:
        bars = [
            {"timestamp": "2026-08-10T02:00:00+00:00", "high": 11, "low": 9, "volume": 10},
            {"timestamp": "2026-08-10T02:02:00+00:00", "high": 12, "low": 10, "volume": 0},
            {"timestamp": "2026-08-10T02:02:00+00:00", "high": 12, "low": 10, "volume": 5},
        ]
        result = analyze_bars(bars, receipt=datetime(2026, 8, 10, 2, 20, tzinfo=UTC))
        self.assertEqual(1, result["missingMinuteCount"])
        self.assertEqual(1, result["duplicateMinuteCount"])
        self.assertEqual(1, result["zeroVolumeBarCount"])
        self.assertEqual(12, result["overnightHigh"])
        self.assertEqual(9, result["overnightLow"])
        self.assertEqual(15, result["cumulativeVolume"])

    def test_repeat_comparison_marks_provisional_changes(self) -> None:
        before = {"SPY": {"providerTimestamp": "x", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}}
        after = {"SPY": {"providerTimestamp": "x", "open": 1, "high": 3, "low": 1, "close": 3, "volume": 15}}
        result = compare_bar_observations(before, after)
        self.assertEqual("PROVISIONAL_CHANGED", result["SPY"]["state"])
        self.assertEqual(["high", "close", "volume"], result["SPY"]["changedFields"])

    def test_adjudication_keeps_authority_unverified(self) -> None:
        symbols = ("SPY", "QQQ", "NVDA")
        latest = {"overnight": {"latestBar": {s: {} for s in symbols}, "latestQuote": {s: {} for s in symbols}, "latestTrade": {s: {} for s in symbols}}, "boats": {"latestBar": {}}}
        history = {s: {"barCount": 5, "cumulativeVolume": 100, "missingMinuteCount": 1} for s in symbols}
        result = adjudicate_probe(symbols=symbols, latest=latest, history=history)
        self.assertEqual("PASS", result["OVERNIGHT_1M_CANDLES"])
        self.assertEqual("DERIVED_OVERNIGHT", result["FEED_IDENTITY"])
        self.assertEqual("USEFUL_WITH_LIMITATIONS", result["CONTEXT_USEFULNESS"])
        self.assertEqual("UNVERIFIED", result["EXECUTION_AUTHORITY"])
        self.assertEqual("NOT_GRANTED", result["CANONICAL_STRATEGY_AUTHORITY"])

    def test_write_proof_is_write_once(self) -> None:
        result = {"adjudication": {"FEED_IDENTITY": "UNKNOWN", "CONTEXT_USEFULNESS": "NOT_USEFUL", "limitations": []}, "observationWindow": {"startedAt": "a", "completedAt": "b"}, "symbols": [], "historicalBars": {}, "executionAuthority": "UNVERIFIED", "canonicalStrategyAuthority": "NOT_GRANTED", "evidenceFingerprint": "abc"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "proof.json"
            markdown_path = root / "proof.md"
            write_proof(result, json_path=json_path, markdown_path=markdown_path)
            with self.assertRaisesRegex(Exception, "write-once"):
                write_proof(result, json_path=json_path, markdown_path=markdown_path)

    def test_module_has_no_order_position_or_mutating_transport_capability(self) -> None:
        import momentum_hunter.alpaca_overnight_probe as module

        source = inspect.getsource(module)
        self.assertNotIn('"/v2/orders', source)
        self.assertNotIn('"/v2/positions', source)
        self.assertNotIn("session.post", source)
        self.assertNotIn("session.delete", source)
        self.assertNotIn("session.patch", source)


if __name__ == "__main__":
    unittest.main()
