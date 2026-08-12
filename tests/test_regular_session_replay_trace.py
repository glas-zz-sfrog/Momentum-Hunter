from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from momentum_hunter.regular_session_replay_trace import (
    BROKER_BOUNDARY,
    CONSTRUCTED_FIXTURE_IDENTITY,
    REAL_REPLAY_IDENTITY,
    RegularSessionReplayError,
    run_regular_session_replay,
)


CENTRAL = ZoneInfo("America/Chicago")


class RegularSessionReplayTraceTests(unittest.TestCase):
    def test_real_shaped_preserved_evidence_reaches_zero_call_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._fixtures(root, ask=100.10, bid=100.09)
            before = {path: path.read_bytes() for path in paths.values()}

            packet = run_regular_session_replay(
                **paths,
                symbol="SPY",
                market_date="2026-07-29",
                prior_session_date="2026-07-28",
                output_root=root / "output",
                clock=lambda: datetime(2026, 8, 12, 17, 0, tzinfo=CENTRAL),
            )

            self.assertTrue(packet["entireDecisionChainReachedBrokerBoundary"])
            self.assertEqual(
                "AUTHORIZED", packet["decisionChain"]["riskGovernor"]["status"]
            )
            self.assertEqual(
                "AUTHORIZED", packet["decisionChain"]["data005bAllocation"]["status"]
            )
            self.assertEqual(
                BROKER_BOUNDARY,
                packet["decisionChain"]["submissionBoundary"]["classification"],
            )
            self.assertEqual(
                0, packet["decisionChain"]["submissionBoundary"]["providerCalls"]
            )
            protection = packet["decisionChain"]["protectiveOrderPlan"]
            self.assertEqual("AWAITING_ACTUAL_FILL", protection["status"])
            self.assertIsNone(protection["quantity"])
            self.assertFalse(protection["submissionPermittedBeforeFillReconciliation"])
            self.assertEqual(REAL_REPLAY_IDENTITY, packet["labelAdjudication"]["thisReplayIdentity"])
            self.assertEqual(
                CONSTRUCTED_FIXTURE_IDENTITY,
                packet["labelAdjudication"]["recommendedProspectiveIdentity"],
            )
            for path, content in before.items():
                self.assertEqual(content, path.read_bytes())

    def test_unreached_real_trigger_stops_before_allocation_or_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._fixtures(root, ask=99.50, bid=99.49)
            packet = run_regular_session_replay(
                **paths,
                symbol="SPY",
                market_date="2026-07-29",
                prior_session_date="2026-07-28",
                output_root=root / "output",
                clock=lambda: datetime(2026, 8, 12, 17, 0, tzinfo=CENTRAL),
            )

            self.assertFalse(packet["entireDecisionChainReachedBrokerBoundary"])
            self.assertIn(
                "PAPER_ENTRY_TRIGGER_NOT_REACHED",
                packet["decisionChain"]["riskGovernor"]["blockers"],
            )
            self.assertEqual(
                "NOT_REACHED", packet["decisionChain"]["data005bAllocation"]["status"]
            )
            self.assertEqual("NOT_CREATED", packet["decisionChain"]["orderIntent"]["status"])
            self.assertEqual(
                "NOT_REACHED_NO_SERIALIZED_ORDER",
                packet["decisionChain"]["submissionBoundary"]["classification"],
            )
            self.assertEqual(0, packet["safety"]["networkCalls"])
            self.assertEqual(0, packet["safety"]["alpacaOrdersSubmitted"])

    def test_replay_separates_original_market_and_replay_times(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._fixtures(root, ask=99.50, bid=99.49)
            replay_time = datetime(2026, 8, 12, 17, 0, tzinfo=CENTRAL)
            packet = run_regular_session_replay(
                **paths,
                symbol="SPY",
                market_date="2026-07-29",
                prior_session_date="2026-07-28",
                output_root=root / "output",
                clock=lambda: replay_time,
            )

            self.assertEqual(
                "2026-07-29T08:35:24-05:00",
                packet["originalMarketTime"]["decisionEvaluationTime"],
            )
            self.assertEqual(replay_time.isoformat(), packet["replayEvaluationTime"]["timestamp"])
            self.assertFalse(packet["replayEvaluationTime"]["controlsDecisionClock"])
            self.assertFalse(packet["retrospectiveTradeCreated"])

    def test_rejects_mixed_legacy_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._fixtures(root, ask=99.50, bid=99.49)
            payload = json.loads(paths["minute_store_path"].read_text(encoding="utf-8"))
            payload["legacySourceMixed"] = True
            paths["minute_store_path"].write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RegularSessionReplayError, "mixed"):
                run_regular_session_replay(
                    **paths,
                    symbol="SPY",
                    market_date="2026-07-29",
                    prior_session_date="2026-07-28",
                    output_root=root / "output",
                )

    def test_module_never_invokes_network_or_broker_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._fixtures(root, ask=100.10, bid=100.09)
            with patch("socket.create_connection", side_effect=AssertionError("network called")):
                packet = run_regular_session_replay(
                    **paths,
                    symbol="SPY",
                    market_date="2026-07-29",
                    prior_session_date="2026-07-28",
                    output_root=root / "output",
                )
            self.assertEqual(0, packet["safety"]["providerCalls"])

    def _fixtures(self, root: Path, *, ask: float, bid: float) -> dict[str, Path]:
        quote = root / "quote.json"
        current = root / "current.json"
        baseline = root / "baseline.json"
        daily = root / "daily.json"
        quote.write_text(
            json.dumps(
                {
                    "proofStatus": "PASS",
                    "checkedAt": "2026-07-29T08:35:24-05:00",
                    "quotes": [
                        {
                            "ask": ask,
                            "bid": bid,
                            "findings": [],
                            "last": bid,
                            "providerAskTimestamp": "2026-07-29T08:35:23-05:00",
                            "providerBidTimestamp": "2026-07-29T08:35:23-05:00",
                            "providerQuoteTimestamp": "2026-07-29T08:35:23-05:00",
                            "quoteAgeSeconds": 1.0,
                            "realtime": True,
                            "securityStatus": "Normal",
                            "session": "regular",
                            "source": "schwab_marketdata_v1_quotes:min_bid_ask_quote_time_v1",
                            "status": "PASS",
                            "symbol": "SPY",
                            "timestamp": "2026-07-29T08:35:23-05:00",
                            "tradingState": "tradable",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        current.write_text(
            json.dumps(self._minute_store("2026-07-29", 99.0)), encoding="utf-8"
        )
        baseline.write_text(
            json.dumps(self._minute_store("2026-07-28", 98.0)), encoding="utf-8"
        )
        daily.write_text(
            json.dumps(
                {
                    "symbol": "SPY",
                    "legacySourceMixed": False,
                    "bars": [
                        {
                            "state": "CANONICAL",
                            "sessionDate": "2026-07-28",
                            "dailyIdentity": "schwab-equity-1d:v1|SPY|2026-07-28",
                            "canonicalCandle": {
                                "symbol": "SPY",
                                "sessionDate": "2026-07-28",
                                "timestamp": "2026-07-27T23:00:00-05:00",
                                "timeframe": "1d",
                                "open": 99.0,
                                "high": 100.0,
                                "low": 98.0,
                                "close": 99.5,
                                "volume": 1000000,
                                "source": "schwab_marketdata_v1_pricehistory:v1",
                                "ohlcvComplete": True,
                            },
                            "historyVersions": [{"versionId": "D" * 64}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {
            "quote_proof_path": quote,
            "minute_store_path": current,
            "baseline_minute_store_path": baseline,
            "daily_store_path": daily,
        }

    def _minute_store(self, session_date: str, base: float) -> dict[str, object]:
        bars = []
        for index in range(5):
            timestamp = f"{session_date}T08:{30 + index:02d}:00-05:00"
            bars.append(
                {
                    "state": "HISTORY_ONLY_GAP_FILL",
                    "minuteIdentity": f"schwab-equity-1m:v1|SPY|{timestamp}",
                    "canonicalCandle": {
                        "symbol": "SPY",
                        "sessionDate": session_date,
                        "timestamp": timestamp,
                        "open": base,
                        "high": base + 0.2,
                        "low": base - 0.2,
                        "close": base + 0.1,
                        "volume": 1000 + index,
                        "source": "schwab_marketdata_v1_pricehistory:v1",
                    },
                    "historyVersions": [{"versionId": str(index) * 64}],
                }
            )
        return {"symbol": "SPY", "legacySourceMixed": False, "bars": bars}


if __name__ == "__main__":
    unittest.main()
