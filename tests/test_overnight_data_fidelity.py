from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.alpaca_paper_onboarding import (
    AlpacaPaperCredentials,
    AlpacaPaperLane,
)
from momentum_hunter.overnight_data_fidelity import (
    FIXED_SYMBOLS,
    OvernightDataFidelityError,
    alpaca_feed_for_phase,
    classify_phase,
    fingerprint,
    load_and_verify_checkpoint,
    measure_alpaca_rest_capacity,
    provider_role,
    require_sanitized,
    run_checkpoint,
    run_schwab_observation,
    session_window,
    summarize_history,
    write_checkpoint,
    _snapshot_symbols,
    _summarize_websocket_control,
    _websocket_subscription_ack,
)


UTC = timezone.utc


class _AlpacaRepository:
    lane = AlpacaPaperLane.CANARY_REALISTIC

    def load(self) -> AlpacaPaperCredentials:
        return AlpacaPaperCredentials("SYNTHETIC-KEY", "SYNTHETIC-SECRET")


class _AlpacaTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str, str]] = []

    def get(self, path, *, params, credentials, feed, data_type):
        del credentials
        self.calls.append((path, dict(params), feed, data_type))
        symbols = tuple(str(params.get("symbols", "SPY")).split(","))
        record = {
            "t": "2026-08-20T05:59:00Z",
            "o": 100.0,
            "h": 101.0,
            "l": 99.0,
            "c": 100.5,
            "v": 10,
            "bp": 100.4,
            "ap": 100.6,
            "p": 100.5,
            "s": 2,
            "x": "V",
        }
        if data_type == "latestBar":
            payload = {"bars": {symbol: record for symbol in symbols}}
        elif data_type == "latestQuote":
            payload = {"quotes": {symbol: record for symbol in symbols}}
        elif data_type == "latestTrade":
            payload = {"trades": {symbol: record for symbol in symbols}}
        elif data_type in {"snapshot", "capacitySnapshot"} or path.endswith("snapshots"):
            payload = {
                "snapshots": {
                    symbol: {"latestTrade": record, "latestQuote": record, "minuteBar": record}
                    for symbol in symbols
                }
            }
        elif data_type == "historicalBars":
            payload = {"bars": [record]}
        elif data_type == "historicalQuotes":
            payload = {"quotes": [record]}
        elif data_type == "historicalTrades":
            payload = {"trades": [record]}
        else:
            payload = {}
        return (
            {
                "provider": "Alpaca Market Data",
                "endpointHost": "data.alpaca.markets",
                "requestMethod": "GET",
                "requestPath": path,
                "feed": feed,
                "dataType": data_type,
                "symbols": list(symbols),
                "requestStart": "2026-08-20T06:00:00+00:00",
                "responseReceipt": "2026-08-20T06:00:01+00:00",
                "apiStatus": 200,
                "apiResult": "SUCCESS",
                "requestIdPresent": True,
                "error": "",
                "credentialValuesIncluded": False,
            },
            payload,
        )


class _ExpiredSchwabRepository:
    def status(self):
        return {"tokenState": "EXPIRED"}

    def load_tokens(self):
        raise AssertionError("Expired tokens must not be loaded.")


class OvernightDataFidelityTests(unittest.TestCase):
    def test_phase_boundaries_are_explicit(self) -> None:
        cases = {
            datetime(2026, 8, 20, 7, 59, tzinfo=UTC): "OVERNIGHT",
            datetime(2026, 8, 20, 8, 0, tzinfo=UTC): "EARLY_PREMARKET",
            datetime(2026, 8, 20, 11, 0, tzinfo=UTC): "STANDARD_PREMARKET",
            datetime(2026, 8, 20, 13, 30, tzinfo=UTC): "REGULAR",
            datetime(2026, 8, 20, 20, 0, tzinfo=UTC): "AFTER_HOURS",
            datetime(2026, 8, 21, 0, 0, tzinfo=UTC): "OVERNIGHT",
        }
        for timestamp, expected in cases.items():
            self.assertEqual(expected, classify_phase(timestamp))
        self.assertEqual("overnight", alpaca_feed_for_phase("OVERNIGHT"))
        self.assertEqual("iex", alpaca_feed_for_phase("REGULAR"))

    def test_overnight_window_starts_at_prior_20_et(self) -> None:
        start, end = session_window(datetime(2026, 8, 20, 6, 0, tzinfo=UTC))
        self.assertEqual("2026-08-20T00:00:00+00:00", start.isoformat())
        self.assertEqual("2026-08-20T06:00:00+00:00", end.isoformat())

    def test_provider_roles_never_blend_authority(self) -> None:
        self.assertEqual(
            "INDICATIVE_ONLY",
            provider_role(provider="ALPACA", feed="overnight", data_type="latestQuote", result="SUCCESS"),
        )
        self.assertEqual(
            "DELAYED_RECONSTRUCTION",
            provider_role(provider="ALPACA", feed="boats", data_type="historicalBars", result="SUCCESS"),
        )
        self.assertEqual(
            "CANONICAL_CANDIDATE",
            provider_role(provider="SCHWAB", feed="schwab", data_type="quotes", result="SUCCESS"),
        )
        self.assertEqual(
            "UNUSABLE",
            provider_role(provider="SCHWAB", feed="schwab", data_type="quotes", result="FAIL"),
        )

    def test_checkpoint_uses_fixed_basket_and_no_financial_capability(self) -> None:
        transport = _AlpacaTransport()
        result = run_checkpoint(
            checkpoint_code="OVERNIGHT_SYNTHETIC",
            observed_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
            include_capacity=False,
            include_websocket=False,
            include_finviz=False,
            alpaca_repository=_AlpacaRepository(),
            alpaca_transport=transport,
            schwab_repository=_ExpiredSchwabRepository(),
        )
        self.assertEqual(list(FIXED_SYMBOLS), result["symbols"])
        self.assertFalse(result["authority"]["strategyAuthorityGranted"])
        self.assertFalse(result["authority"]["executionAuthorityGranted"])
        self.assertEqual("UNAVAILABLE", result["safety"]["orderCapability"])
        self.assertEqual("NOT_RUN_SHARED_TOKEN_NOT_ACTIVE", result["providers"]["schwab"]["status"])
        rendered = json.dumps(result)
        self.assertNotIn("SYNTHETIC-KEY", rendered)
        self.assertNotIn("SYNTHETIC-SECRET", rendered)
        self.assertTrue(all("account" not in call[0] for call in transport.calls))
        self.assertTrue(all("orders" not in call[0] for call in transport.calls))

    def test_capacity_records_measured_counts(self) -> None:
        transport = _AlpacaTransport()
        result = measure_alpaca_rest_capacity(
            client=transport,
            credentials=AlpacaPaperCredentials("KEY", "SECRET"),
            feed="overnight",
            universe_source=None,
        )
        self.assertEqual("MEASURED", result["status"])
        self.assertEqual(31, result["largestAcceptedSingleRequest"])
        self.assertEqual(31, result["largestSuccessfulCoverageRequest"])
        self.assertEqual([30, 31], [row["requestedSymbolCount"] for row in result["measurements"]])

    def test_capacity_accepts_both_snapshot_response_shapes(self) -> None:
        requested = ("SPY", "QQQ")
        expected = ("QQQ", "SPY")
        nested = {"snapshots": {"SPY": {}, "QQQ": {}}}
        top_level = {"SPY": {}, "QQQ": {}}
        self.assertEqual(expected, _snapshot_symbols(nested, requested))
        self.assertEqual(expected, _snapshot_symbols(top_level, requested))

    def test_websocket_subscription_ack_requires_all_requested_symbols(self) -> None:
        payload = [{"T": "subscription", "bars": ["SPY"], "quotes": ["SPY", "QQQ"], "trades": []}]
        self.assertTrue(_websocket_subscription_ack(payload, ("SPY", "QQQ"), ("quotes",)))
        self.assertFalse(_websocket_subscription_ack(payload, ("SPY", "QQQ"), ("bars", "quotes")))
        self.assertFalse(_websocket_subscription_ack(payload, ("SPY", "QQQ", "NVDA")))
        summary = _summarize_websocket_control(payload)
        self.assertEqual("subscription", summary[0]["type"])
        self.assertEqual(2, summary[0]["quotesCount"])
        self.assertNotIn("S", summary[0])

    def test_history_summary_preserves_sparse_identity_without_fabrication(self) -> None:
        rows = [
            {"t": "2026-08-20T05:00:00Z", "v": 10, "x": "V"},
            {"t": "2026-08-20T05:02:00Z", "v": 12, "x": "V"},
            {"t": "2026-08-20T05:02:00Z", "v": 2, "x": "V"},
        ]
        summary = summarize_history(rows, family="bars")
        self.assertEqual(3, summary["recordCount"])
        self.assertEqual(1, summary["duplicateTimestampCount"])
        self.assertEqual(24.0, summary["volumeTotal"])
        self.assertNotIn("missingMinuteCount", summary)

    def test_expired_schwab_token_is_not_refreshed_or_loaded(self) -> None:
        result = run_schwab_observation(
            observed_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
            repository=_ExpiredSchwabRepository(),
            quote_transport=None,
            history_transport=None,
        )
        self.assertEqual("NOT_RUN_SHARED_TOKEN_NOT_ACTIVE", result["status"])
        self.assertFalse(result["tokenRefreshAttempted"])

    def test_write_once_checkpoint_and_fingerprint_verification(self) -> None:
        transport = _AlpacaTransport()
        result = run_checkpoint(
            checkpoint_code="WRITE_ONCE",
            observed_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
            include_finviz=False,
            alpaca_repository=_AlpacaRepository(),
            alpaca_transport=transport,
            schwab_repository=_ExpiredSchwabRepository(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            json_path, _, _, _ = write_checkpoint(result, output_root=root)
            loaded = load_and_verify_checkpoint(json_path)
            self.assertEqual(fingerprint(result), loaded["evidenceFingerprint"])
            with self.assertRaisesRegex(OvernightDataFidelityError, "write-once"):
                write_checkpoint(result, output_root=root)

    def test_sanitation_rejects_secret_and_forbidden_route(self) -> None:
        with self.assertRaises(OvernightDataFidelityError):
            require_sanitized({"safe": "SECRET"}, forbidden_values=("SECRET",))
        with self.assertRaises(OvernightDataFidelityError):
            require_sanitized({"path": "/v2/orders"}, forbidden_values=())

    def test_websocket_runner_is_injected_without_exposing_credentials(self) -> None:
        def websocket_runner(*, credentials):
            self.assertEqual("SYNTHETIC-KEY", credentials.key_id)
            return {
                "status": "PASS",
                "requestedSymbolCount": 30,
                "credentialsIncluded": False,
            }

        result = run_checkpoint(
            checkpoint_code="WEBSOCKET_SYNTHETIC",
            observed_at=datetime(2026, 8, 20, 6, 0, tzinfo=UTC),
            include_websocket=True,
            include_finviz=False,
            alpaca_repository=_AlpacaRepository(),
            alpaca_transport=_AlpacaTransport(),
            schwab_repository=_ExpiredSchwabRepository(),
            websocket_runner=websocket_runner,
        )
        self.assertEqual("PASS", result["providers"]["alpaca"]["websocket"]["status"])
        self.assertNotIn("SYNTHETIC-KEY", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
