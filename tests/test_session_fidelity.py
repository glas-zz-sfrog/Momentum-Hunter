from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from momentum_hunter.schwab_candle_observer import GuardedStreamerAccess
from momentum_hunter.session_fidelity import (
    CHECKPOINTS,
    SYMBOLS,
    SessionFidelityError,
    adjudicate_schwab,
    fingerprint,
    load_and_verify,
    require_checkpoint_start,
    run_schwab_checkpoint,
    write_json_once,
)


class _Guard:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, ending: str) -> GuardedStreamerAccess:
        self.calls.append(ending)
        return GuardedStreamerAccess(
            access_token="test-access-token",
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class _Quotes:
    def __init__(self, now: object, *, stale: bool = False) -> None:
        self.now = now
        self.stale = stale

    def fetch_quotes_with_clock(self, token: str, symbols: object) -> object:
        self.token = token
        self.symbols = tuple(symbols)
        timestamp = self.now - timedelta(hours=2) if self.stale else self.now
        quotes = {
            symbol: SimpleNamespace(
                provider_quote_timestamp=timestamp.isoformat(),
                provider_bid_timestamp=timestamp.isoformat(),
                provider_ask_timestamp=timestamp.isoformat(),
                bid=100.0,
                ask=100.02,
                last=100.01,
                volume=1000,
                realtime=not self.stale,
                security_status="Normal",
                source="schwab_marketdata_v1_quotes:v1",
            )
            for symbol in SYMBOLS
        }
        return SimpleNamespace(
            quotes=quotes,
            clock_skew_proof={"responseReceivedAt": self.now.isoformat()},
        )


class _Observer:
    def __init__(self, *, stale: bool = False, **_kwargs: object) -> None:
        self.stale = stale

    def observe(self, options: object) -> dict[str, object]:
        age = 7200.0 if self.stale else 30.0
        return {
            "candles": [
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "ohlcvComplete": True,
                    "ageAtEvaluationSeconds": age,
                    "volume": 100,
                }
                for symbol in options.symbols
            ],
            "streamStatus": "PASS",
            "priceHistoryStatus": "PASS",
            "productionDataWritten": False,
        }


class SessionFidelityTests(unittest.TestCase):
    def test_checkpoint_matrix_is_fixed_and_reuses_d_and_i(self) -> None:
        self.assertEqual(tuple(CHECKPOINTS), tuple("ABCDEFGHI"))
        self.assertEqual(SYMBOLS, ("SPY", "QQQ", "NVDA"))
        self.assertTrue(CHECKPOINTS["D"].externally_supplied)
        self.assertTrue(CHECKPOINTS["I"].externally_supplied)
        self.assertEqual(CHECKPOINTS["E"].duration_seconds, 180)
        for code in "ABCFGH":
            self.assertEqual(CHECKPOINTS[code].duration_seconds, 300)

    def test_checkpoint_window_fails_closed(self) -> None:
        target = CHECKPOINTS["E"].target_central
        self.assertEqual(require_checkpoint_start("E", target).code, "E")
        with self.assertRaises(SessionFidelityError):
            require_checkpoint_start("E", target - timedelta(seconds=1))
        with self.assertRaises(SessionFidelityError):
            require_checkpoint_start("E", target + timedelta(minutes=7))
        with self.assertRaises(SessionFidelityError):
            require_checkpoint_start("D", CHECKPOINTS["D"].target_central)

    def test_schwab_checkpoint_produces_sanitized_high_fidelity_evidence(self) -> None:
        now = CHECKPOINTS["E"].target_central
        guard = _Guard()
        result = run_schwab_checkpoint(
            "E",
            now=now,
            utc_clock=lambda: now,
            access_guard=guard,
            quote_transport=_Quotes(now),
            observer_factory=lambda **kwargs: _Observer(**kwargs),
        )
        self.assertEqual(result["adjudication"]["classification"], "HIGH_FIDELITY")
        self.assertEqual(result["adjudication"]["QUOTE_AUTHORITY"], "SESSION_HIGH_FIDELITY")
        self.assertEqual(result["adjudication"]["CANDLE_AUTHORITY"], "SESSION_HIGH_FIDELITY")
        self.assertFalse(result["strategyAuthorityGranted"])
        self.assertFalse(result["executionAuthorityGranted"])
        self.assertFalse(result["positionsRequested"])
        self.assertFalse(result["ordersRequested"])
        self.assertEqual(result["orderTransmission"], "UNAVAILABLE")
        rendered = json.dumps(result)
        self.assertNotIn("test-access-token", rendered)
        self.assertEqual(result["evidenceFingerprint"], fingerprint(result))
        self.assertEqual(guard.calls, ["2573"])

    def test_stale_evidence_is_not_authoritative(self) -> None:
        quotes = {
            symbol: {
                "bid": 100,
                "ask": 101,
                "quoteAgeSeconds": 7200,
                "bidAgeSeconds": 7200,
                "askAgeSeconds": 7200,
            }
            for symbol in SYMBOLS
        }
        stream = {
            "candles": [
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "ohlcvComplete": True,
                    "ageAtEvaluationSeconds": 7200,
                    "volume": 100,
                }
                for symbol in SYMBOLS
            ]
        }
        result = adjudicate_schwab(stream, quotes)
        self.assertEqual(result["classification"], "STALE")
        self.assertEqual(result["QUOTE_AUTHORITY"], "NOT_PROVEN")
        self.assertEqual(result["CANDLE_AUTHORITY"], "NOT_PROVEN")
        self.assertFalse(result["strategyAuthorityGranted"])

    def test_write_once_and_fingerprint_verification(self) -> None:
        evidence = {
            "taskId": "SESSION-FIDELITY-001",
            "adjudication": {"classification": "UNAVAILABLE"},
            "ordersRequested": False,
            "positionsRequested": False,
        }
        evidence["evidenceFingerprint"] = fingerprint(evidence)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof.json"
            proof_hash = write_json_once(evidence, output)
            self.assertEqual(len(proof_hash), 64)
            self.assertEqual(load_and_verify(output), evidence)
            with self.assertRaises(SessionFidelityError):
                write_json_once(evidence, output)
            tampered = json.loads(output.read_text(encoding="utf-8"))
            tampered["ordersRequested"] = True
            output.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(SessionFidelityError):
                load_and_verify(output)

    def test_tooling_has_no_order_position_or_live_endpoint_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        alpaca = (root / "tools" / "run_session_fidelity_alpaca.py").read_text(encoding="utf-8")
        runner = (root / "tools" / "run_session_fidelity_checkpoint.py").read_text(encoding="utf-8")
        installer = (root / "tools" / "install_session_fidelity_tasks.ps1").read_text(encoding="utf-8")
        combined = alpaca + runner
        for forbidden in (
            "paper-api.alpaca.markets",
            "api.alpaca.markets",
            "/v2/orders",
            "/v2/positions",
            "preview_order",
            "submit_order",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn('SNAPSHOT_PATH = "/v2/stocks/snapshots"', alpaca)
        self.assertIn('FEED = "iex"', alpaca)
        self.assertNotIn("New-ScheduledTaskTrigger -Daily", installer)
        settings = installer.split("$settings =", 1)[1].split("if (-not $Execute)", 1)[0]
        self.assertNotIn("-StartWhenAvailable", settings)
        self.assertIn('reusedExistingLanes = @("D_OPENING_CAPTURE", "I_OVERNIGHT_002")', installer)

    def test_alpaca_adapter_is_context_only_and_redacts_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        adapter_path = root / "tools" / "run_session_fidelity_alpaca.py"
        spec = importlib.util.spec_from_file_location("session_fidelity_alpaca_test", adapter_path)
        assert spec is not None and spec.loader is not None
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)

        secret = SimpleNamespace(key_id="synthetic-key", secret_key="synthetic-secret")

        class Lane:
            CANARY_REALISTIC = "CANARY_REALISTIC"

        class Repository:
            def __init__(self, *, lane: object) -> None:
                self.lane = lane

            def load(self) -> object:
                return secret

        target = CHECKPOINTS["A"].target_central

        class Transport:
            def get(
                self,
                path: str,
                *,
                params: object,
                credentials: object,
                feed: str,
                data_type: str,
            ) -> tuple[dict[str, object], dict[str, object]]:
                self.credentials = credentials
                receipt = target.isoformat()
                if data_type == "snapshot":
                    payload = {"snapshots": {symbol: {} for symbol in SYMBOLS}}
                else:
                    payload = {"bars": []}
                return {
                    "requestPath": path,
                    "responseReceipt": receipt,
                    "feed": feed,
                    "dataType": data_type,
                }, payload

        def parse_latest(
            _data_type: str,
            _payload: object,
            *,
            symbols: object,
            receipt: object,
            feed: str,
        ) -> dict[str, object]:
            self.assertEqual(feed, "iex")
            return {
                symbol: {
                    "latestQuote": {
                        "bid": 100,
                        "ask": 101,
                        "observedAgeSeconds": 1,
                        "latencyClassification": "STALE",
                    },
                    "minuteBar": {
                        "volume": 500,
                        "observedAgeSeconds": 30,
                        "latencyClassification": "STALE",
                    },
                    "latestTrade": {
                        "price": 100.5,
                        "observedAgeSeconds": 1,
                        "latencyClassification": "STALE",
                    },
                }
                for symbol in symbols
            }

        fake_probe = SimpleNamespace(
            AlpacaPaperLane=Lane,
            AlpacaPaperCredentialRepository=Repository,
            AlpacaOvernightTransport=Transport,
            _parse_timestamp=lambda value: target,
            _parse_latest_payload=parse_latest,
            _parse_historical_bars=lambda payload, symbol: [],
            analyze_bars=lambda bars, receipt: {"barCount": 0, "bars": []},
            _assert_sanitized=lambda result, credentials: None,
        )
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            module = source_root / "momentum_hunter" / "alpaca_overnight_probe.py"
            module.parent.mkdir(parents=True)
            module.write_text("# synthetic frozen module\n", encoding="utf-8")
            with mock.patch.object(adapter, "_load_frozen_probe", return_value=fake_probe):
                result = adapter.run(
                    "A",
                    source_root=source_root,
                    now=target,
                    sleeper=lambda _seconds: None,
                )
        self.assertEqual(result["adjudication"]["classification"], "HIGH_FIDELITY")
        self.assertEqual(result["adjudication"]["QUOTE_AUTHORITY"], "RESEARCH_CONTEXT_ONLY")
        self.assertFalse(result["strategyAuthorityGranted"])
        self.assertFalse(result["executionAuthorityGranted"])
        self.assertFalse(result["ordersRequested"])
        self.assertFalse(result["positionsRequested"])
        quote = result["finalSnapshot"]["SPY"]["latestQuote"]
        self.assertEqual(quote["sourceParserLatencyClassification"], "STALE")
        self.assertEqual(quote["latencyClassification"], "FRESH_CONTEXT")
        rendered = json.dumps(result)
        self.assertNotIn(secret.key_id, rendered)
        self.assertNotIn(secret.secret_key, rendered)


if __name__ == "__main__":
    unittest.main()
