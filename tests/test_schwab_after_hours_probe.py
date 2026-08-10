from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.schwab_after_hours_probe import (
    SYMBOLS,
    SchwabAfterHoursProbe,
    SchwabAfterHoursProbeError,
    _fingerprint,
    adjudicate_after_hours_proof,
    build_quote_evidence,
    load_existing_proof,
    require_after_hours_window,
)
from momentum_hunter.schwab_candle_observer import write_proof_once


UTC = timezone.utc


def _proof(*, difference_fields: tuple[str, ...] = (), stale: bool = False) -> dict[str, object]:
    age = 240.0 if stale else 80.0
    candles = [
        {
            "symbol": symbol,
            "status": "PASS",
            "ohlcvComplete": True,
            "session": "extended",
            "ageAtEvaluationSeconds": age,
        }
        for symbol in SYMBOLS
    ]
    quotes = {
        symbol: {
            "bid": 10.0,
            "ask": 10.1,
            "quoteAgeSeconds": 2.0,
            "bidAgeSeconds": 3.0,
            "askAgeSeconds": 1.0,
        }
        for symbol in SYMBOLS
    }
    rows = [
        {
            "symbol": "SPY",
            "status": "CORRECTED_OR_DIFFERENT" if difference_fields else "MATCH",
            "changedFields": list(difference_fields),
        }
    ]
    return {
        "requestedSymbols": list(SYMBOLS),
        "candles": candles,
        "afterHoursQuotes": quotes,
        "streamStatus": "PASS",
        "priceHistoryStatus": "PASS",
        "streamHistoryReconciliation": {
            "comparableMinuteCount": 3,
            "rows": rows,
        },
        "productionDataWritten": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }


class SchwabAfterHoursProbeTests(unittest.TestCase):
    def test_wrapper_authorizes_once_and_adjudicates_synthetic_observer(self) -> None:
        observed_at = datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
        quote = SimpleNamespace(
            provider_quote_timestamp=(observed_at - timedelta(seconds=2)).isoformat(),
            provider_bid_timestamp=(observed_at - timedelta(seconds=3)).isoformat(),
            provider_ask_timestamp=(observed_at - timedelta(seconds=1)).isoformat(),
            source="synthetic",
            bid=1.0,
            ask=1.1,
            last=1.05,
            volume=100,
            realtime=True,
            security_status="Normal",
        )
        access = SimpleNamespace(
            access_token="forbidden-synthetic-token",
            account_ending="2573",
        )

        class Guard:
            calls = 0

            def authorize(self, ending: str) -> object:
                self.calls += 1
                self.assertion = ending
                return access

        class QuoteTransport:
            def fetch_quotes_with_clock(self, token: str, symbols: tuple[str, ...]) -> object:
                self.token = token
                self.symbols = symbols
                return SimpleNamespace(
                    quotes={symbol: quote for symbol in SYMBOLS},
                    clock_skew_proof={"responseReceivedAt": observed_at.isoformat()},
                )

        class Observer:
            def __init__(self, *, access_guard: object, utc_clock: object) -> None:
                self.access_guard = access_guard

            def observe(self, options: object) -> dict[str, object]:
                self.access_guard.authorize("2573")
                proof = _proof()
                proof["proofFingerprint"] = "BASE"
                return proof

        guard = Guard()
        transport = QuoteTransport()
        result = SchwabAfterHoursProbe(
            access_guard=guard,
            quote_transport=transport,
            observer_factory=Observer,
            utc_clock=lambda: observed_at,
        ).observe(
            expected_session_date=date(2026, 8, 11),
            duration_seconds=300,
            attempt_label="OPEN",
        )
        self.assertEqual(1, guard.calls)
        self.assertEqual("2573", guard.assertion)
        self.assertEqual("forbidden-synthetic-token", transport.token)
        self.assertEqual(SYMBOLS, transport.symbols)
        self.assertEqual(
            "SCHWAB_AFTER_HOURS_PROVEN",
            result["afterHoursAdjudication"]["classification"],
        )
        self.assertNotIn("forbidden-synthetic-token", str(result))

    def test_tuesday_after_hours_window_is_allowed(self) -> None:
        observed = datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
        eastern = require_after_hours_window(observed, date(2026, 8, 11))
        self.assertEqual(16, eastern.hour)

    def test_regular_premarket_weekend_and_wrong_date_are_rejected(self) -> None:
        cases = (
            (datetime(2026, 8, 11, 13, 0, tzinfo=UTC), date(2026, 8, 11)),
            (datetime(2026, 8, 11, 16, 0, tzinfo=UTC), date(2026, 8, 11)),
            (datetime(2026, 8, 9, 21, 0, tzinfo=UTC), date(2026, 8, 9)),
            (datetime(2026, 8, 11, 20, 5, tzinfo=UTC), date(2026, 8, 12)),
        )
        for observed, expected in cases:
            with self.subTest(observed=observed, expected=expected):
                with self.assertRaises(SchwabAfterHoursProbeError):
                    require_after_hours_window(observed, expected)

    def test_quote_evidence_preserves_provider_and_receipt_clocks(self) -> None:
        receipt = datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
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
        evidence = build_quote_evidence(
            {symbol: quote for symbol in SYMBOLS},
            receipt=receipt,
        )
        self.assertEqual(3.0, evidence["SPY"]["bidAgeSeconds"])
        self.assertEqual(1.0, evidence["SPY"]["askAgeSeconds"])
        self.assertEqual("SCHWAB", evidence["SPY"]["provider"])

    def test_complete_exact_evidence_is_proven(self) -> None:
        result = adjudicate_after_hours_proof(_proof())
        self.assertEqual("SCHWAB_AFTER_HOURS_PROVEN", result["classification"])
        self.assertEqual([], result["failedChecks"])

    def test_volume_only_difference_is_proven_with_limitations(self) -> None:
        result = adjudicate_after_hours_proof(_proof(difference_fields=("volume",)))
        self.assertEqual(
            "SCHWAB_AFTER_HOURS_PROVEN_WITH_LIMITATIONS",
            result["classification"],
        )
        self.assertEqual(1, result["volumeDifferenceCount"])

    def test_ohlc_difference_fails_and_never_grants_canonicality(self) -> None:
        result = adjudicate_after_hours_proof(_proof(difference_fields=("close",)))
        self.assertEqual("SCHWAB_AFTER_HOURS_DATA_INSUFFICIENT", result["classification"])
        self.assertIn("OHLC_RECONCILIATION", result["failedChecks"])
        self.assertFalse(result["canonicalityGranted"])

    def test_stale_or_missing_evidence_fails(self) -> None:
        stale = adjudicate_after_hours_proof(_proof(stale=True))
        self.assertIn("FRESH_EXTENDED_HOURS_OHLCV", stale["failedChecks"])
        missing = _proof()
        missing["afterHoursQuotes"].pop("NVDA")
        result = adjudicate_after_hours_proof(missing)
        self.assertIn("FRESH_QUOTES", result["failedChecks"])

    def test_existing_proof_verifies_fingerprint_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proof.json"
            proof = {
                **_proof(),
                "afterHoursProbeType": "SCHWAB_AFTER_HOURS_CANDLE_PROOF",
            }
            proof["afterHoursAdjudication"] = adjudicate_after_hours_proof(proof)
            proof["proofFingerprint"] = _fingerprint(proof)
            write_proof_once(proof, path)
            self.assertEqual(proof, load_existing_proof(path))
            path.write_text(path.read_text().replace('"SPY"', '"BAD"', 1))
            with self.assertRaisesRegex(SchwabAfterHoursProbeError, "fingerprint"):
                load_existing_proof(path)

    def test_runtime_surface_has_no_order_or_mutating_http_capability(self) -> None:
        import momentum_hunter.schwab_after_hours_probe as module

        source = inspect.getsource(module)
        self.assertNotIn("session.post", source)
        self.assertNotIn("session.put", source)
        self.assertNotIn("session.patch", source)
        self.assertNotIn("session.delete", source)
        self.assertNotIn('"/orders', source)
        self.assertNotIn('"/positions', source)
        self.assertNotIn("FakeBroker", source)

    def test_runner_pins_clean_git_and_module_identity(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner = (root / "tools" / "run_schwab_after_hours_probe.ps1").read_text()
        installer = (
            root / "tools" / "install_schwab_after_hours_probe_tasks.ps1"
        ).read_text()
        self.assertIn("ExpectedGitCommit", runner)
        self.assertIn("ExpectedModuleSha256", runner)
        self.assertIn("status --porcelain", runner)
        self.assertIn("ExpectedGitCommit", installer)
        self.assertIn("ExpectedModuleSha256", installer)


if __name__ == "__main__":
    unittest.main()
