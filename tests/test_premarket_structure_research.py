from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.premarket_structure_research import (
    CANONICAL_SOURCE,
    EASTERN,
    PremarketStructureResearchError,
    ResearchBar,
    aggregate_bars,
    build_decision_packet,
    build_outcome_packet,
    classify_full_structure,
    load_research_bars,
    packet_fingerprint,
)


class PremarketStructureResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / (
            f"_test-premarket-structure-{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_full_structure_can_create_distinct_continuation_setup(self) -> None:
        premarket, last_15, opening = structured_windows("AAA")

        result = classify_full_structure(
            symbol="AAA",
            original_entry=100.0,
            original_stop=96.0,
            original_target=108.0,
            original_setup_fingerprint="ORIGINAL-A",
            ask=111.05,
            atr=4.0,
            premarket=premarket,
            last_15=last_15,
            opening=opening,
        )

        self.assertTrue(result["newSetup"])
        self.assertEqual("CONTINUATION_BREAKOUT", result["family"])
        self.assertEqual(111.0, result["trigger"])
        self.assertEqual("ORIGINAL-A", result["predecessorSetupFingerprint"])
        self.assertEqual("WITHIN_0_25_PCT", result["extensionStatus"])
        self.assertEqual("ALLOW", result["hypotheticalDecision"])

    def test_recent_vertical_premarket_high_does_not_create_new_setup(self) -> None:
        premarket, last_15, opening = structured_windows("AAA")
        last_15[-1] = bar("AAA", "2026-08-13T09:29:00-04:00", 109.0, 110.5, 108.9, 110.4)
        premarket = premarket[:-15] + last_15

        result = classify_full_structure(
            symbol="AAA",
            original_entry=100.0,
            original_stop=96.0,
            original_target=108.0,
            original_setup_fingerprint="ORIGINAL-A",
            ask=111.05,
            atr=4.0,
            premarket=premarket,
            last_15=last_15,
            opening=opening,
        )

        self.assertFalse(result["newSetup"])
        self.assertEqual("NO_NEW_STRUCTURE", result["family"])
        self.assertEqual("BLOCK", result["hypotheticalDecision"])

    def test_opening_cross_does_not_reopen_original_or_create_successor(self) -> None:
        premarket, last_15, opening = structured_windows("AAA")
        premarket = [
            ResearchBar(
                symbol=item.symbol,
                timestamp=item.timestamp,
                open=item.open - 20.0,
                high=item.high - 20.0,
                low=item.low - 20.0,
                close=item.close - 20.0,
                volume=item.volume,
                source=item.source,
                state=item.state,
                first_received_at=item.first_received_at,
                identity=item.identity,
            )
            for item in premarket
        ]
        last_15 = premarket[-15:]
        opening = [
            bar("AAA", "2026-08-13T09:30:00-04:00", 99.0, 100.5, 98.9, 100.2),
            bar("AAA", "2026-08-13T09:31:00-04:00", 100.2, 101.0, 100.0, 100.7),
            bar("AAA", "2026-08-13T09:32:00-04:00", 100.7, 101.5, 100.6, 101.2),
            bar("AAA", "2026-08-13T09:33:00-04:00", 101.2, 102.0, 101.0, 101.8),
            bar("AAA", "2026-08-13T09:34:00-04:00", 101.8, 102.1, 101.4, 101.6),
        ]

        result = classify_full_structure(
            symbol="AAA",
            original_entry=100.0,
            original_stop=96.0,
            original_target=108.0,
            original_setup_fingerprint="ORIGINAL-A",
            ask=99.95,
            atr=4.0,
            premarket=premarket,
            last_15=last_15,
            opening=opening,
        )

        self.assertEqual("NO_NEW_STRUCTURE", result["family"])
        self.assertEqual("BLOCK", result["hypotheticalDecision"])
        self.assertEqual(
            "ORIGINAL_LEVEL_CROSSED_DURING_OPENING_NO_SUCCESSOR_STRUCTURE",
            result["chronology"],
        )

    def test_aggregate_uses_completed_bars_and_bar_derived_vwap(self) -> None:
        bars = [
            bar("AAA", "2026-08-13T09:15:00-04:00", 10.0, 10.5, 9.5, 10.2, 100),
            bar("AAA", "2026-08-13T09:16:00-04:00", 10.2, 11.0, 10.0, 10.8, 300),
        ]

        result = aggregate_bars(bars)

        self.assertEqual(2, result["barCount"])
        self.assertEqual(10.0, result["open"])
        self.assertEqual(11.0, result["high"])
        self.assertEqual(9.5, result["low"])
        self.assertEqual(10.8, result["close"])
        self.assertEqual(400, result["volume"])
        self.assertAlmostEqual(10.466667, result["vwapApprox"], places=6)

    def test_loader_rejects_legacy_source_mixing(self) -> None:
        path = self.root / "AAA.json"
        payload = partition_payload("AAA", [bar("AAA", "2026-08-13T09:30:00-04:00", 10, 11, 9, 10)])
        payload["legacySourceMixed"] = True
        write_json(path, payload)

        with self.assertRaises(PremarketStructureResearchError):
            load_research_bars(path, expected_symbol="AAA")

    def test_loader_rejects_tampered_minute_identity(self) -> None:
        path = self.root / "AAA.json"
        payload = partition_payload(
            "AAA", [bar("AAA", "2026-08-13T09:30:00-04:00", 10, 11, 9, 10)]
        )
        payload["bars"][0]["minuteIdentity"] = "schwab-equity-1m:v1|AAA|ALTERED"
        write_json(path, payload)

        with self.assertRaises(PremarketStructureResearchError):
            load_research_bars(path, expected_symbol="AAA")

    def test_loader_rejects_canonical_candle_not_in_final_history(self) -> None:
        path = self.root / "AAA.json"
        payload = partition_payload(
            "AAA", [bar("AAA", "2026-08-13T09:30:00-04:00", 10, 11, 9, 10)]
        )
        payload["bars"][0]["historyVersions"][-1]["candle"] = dict(
            payload["bars"][0]["historyVersions"][-1]["candle"]
        )
        payload["bars"][0]["canonicalCandle"]["close"] = 10.5
        write_json(path, payload)

        with self.assertRaises(PremarketStructureResearchError):
            load_research_bars(path, expected_symbol="AAA")

    def test_pass_one_excludes_post_cutoff_price_action(self) -> None:
        trade_plan = self.root / "trade-plan.json"
        capture = self.root / "capture.json"
        backfill = self.root / "backfill.json"
        minute_root = self.root / "minute"
        output = self.root / "decision.json"
        write_json(trade_plan, report_payload())
        write_json(capture, {"status": "CAPTURED", "market_regime": "bull"})
        write_json(
            backfill,
            {
                "status": "COMPLETE",
                "symbols": [
                    {"symbol": symbol}
                    for symbol in ("CRWV", "NBIS", "IREN", "HPE", "SMCI", "SPY", "QQQ", "IWM")
                ],
            },
        )
        bars = complete_window("AAA")
        bars.append(bar("AAA", "2026-08-13T09:35:00-04:00", 500, 999, 1, 900))
        for symbol in ("CRWV", "NBIS", "IREN", "HPE", "SMCI", "SPY", "QQQ", "IWM"):
            symbol_bars = [replace_symbol(item, symbol) for item in bars]
            write_json(
                minute_root / "2026-08-13" / f"{symbol}.json",
                partition_payload(symbol, symbol_bars),
            )
        source_paths = [trade_plan, capture, backfill] + sorted(
            (minute_root / "2026-08-13").glob("*.json")
        )
        source_hashes = {path: sha256(path) for path in source_paths}

        result = build_decision_packet(
            trade_plan_path=trade_plan,
            capture_path=capture,
            minute_store_root=minute_root,
            backfill_result_path=backfill,
            output_path=output,
        )

        for candidate in result["candidates"]:
            self.assertLess(candidate["premarket"]["high"], 500)
            self.assertLess(candidate["openingRange"]["high"], 500)
        for benchmark in result["marketRegime"]["benchmarks"]:
            self.assertLess(benchmark["openingRange"]["high"], 500)
        self.assertFalse(result["outcomeEvidenceInspected"])
        self.assertEqual(result["decisionFingerprint"], packet_fingerprint(result))
        self.assertTrue(output.exists())
        output_hash = sha256(output)

        repeated = build_decision_packet(
            trade_plan_path=trade_plan,
            capture_path=capture,
            minute_store_root=minute_root,
            backfill_result_path=backfill,
            output_path=output,
        )

        self.assertEqual(result, repeated)
        self.assertEqual(output_hash, sha256(output))
        self.assertEqual(source_hashes, {path: sha256(path) for path in source_paths})

        tampered = json.loads(output.read_text(encoding="utf-8"))
        tampered["decisionFingerprint"] = "ALTERED"
        write_json(output, tampered)
        with self.assertRaises(PremarketStructureResearchError):
            build_decision_packet(
                trade_plan_path=trade_plan,
                capture_path=capture,
                minute_store_root=minute_root,
                backfill_result_path=backfill,
                output_path=output,
            )
        self.assertEqual(source_hashes, {path: sha256(path) for path in source_paths})

    def test_pass_two_rejects_tampered_decision_packet(self) -> None:
        decision = self.root / "decision.json"
        payload = {
            "outcomeEvidenceInspected": False,
            "completedBarCutoff": "2026-08-13T09:35:00-04:00",
            "sessionDate": "2026-08-13",
            "sourceHashes": {},
            "candidates": [],
        }
        payload["decisionFingerprint"] = packet_fingerprint(payload)
        payload["sessionDate"] = "2026-08-14"
        write_json(decision, payload)

        with self.assertRaises(PremarketStructureResearchError):
            build_outcome_packet(
                decision_path=decision,
                minute_store_root=self.root / "minute",
                output_path=self.root / "outcome.json",
            )

    def test_pass_two_uses_frozen_allow_and_reports_mfe_mae(self) -> None:
        minute_root = self.root / "minute"
        partition = minute_root / "2026-08-13" / "AAA.json"
        later = [
            bar("AAA", "2026-08-13T09:35:00-04:00", 10.1, 10.8, 9.9, 10.5),
            bar("AAA", "2026-08-13T09:36:00-04:00", 10.5, 12.2, 10.4, 12.0),
        ]
        write_json(partition, partition_payload("AAA", later))
        decision = self.root / "decision.json"
        payload = {
            "outcomeEvidenceInspected": False,
            "completedBarCutoff": "2026-08-13T09:35:00-04:00",
            "sessionDate": "2026-08-13",
            "sourceHashes": {"minute:AAA": sha256(partition)},
            "candidates": [
                {
                    "symbol": "AAA",
                    "decisionAt": "2026-08-13T09:35:00-04:00",
                    "decisionQuote": {"ask": 10.0},
                    "models": {
                        "fullStructure": {
                            "hypotheticalDecision": "ALLOW",
                            "setupId": "SETUP-A",
                            "stop": 9.5,
                            "targets": [11.0],
                        }
                    },
                }
            ],
        }
        payload["decisionFingerprint"] = packet_fingerprint(payload)
        write_json(decision, payload)

        result = build_outcome_packet(
            decision_path=decision,
            minute_store_root=minute_root,
            output_path=self.root / "outcome.json",
        )

        candidate = result["candidates"][0]
        self.assertEqual(22.0, candidate["mfePct"])
        self.assertEqual(-1.0, candidate["maePct"])
        self.assertEqual("TARGET_FIRST", candidate["targetStopSequence"])
        self.assertFalse(candidate["currentMhRejectionAvoidedHypotheticalLoss"])
        self.assertEqual(
            "POST_DECISION_MARKET_OBSERVATION_NOT_A_TRADE",
            candidate["postDecisionObservation"]["classification"],
        )

    def test_pass_two_stops_excursion_measurement_at_stop(self) -> None:
        minute_root = self.root / "minute"
        partition = minute_root / "2026-08-13" / "AAA.json"
        later = [
            bar("AAA", "2026-08-13T09:35:00-04:00", 10.0, 10.4, 9.8, 10.2),
            bar("AAA", "2026-08-13T09:36:00-04:00", 10.2, 10.3, 9.4, 9.5),
            bar("AAA", "2026-08-13T09:37:00-04:00", 9.5, 20.0, 1.0, 15.0),
        ]
        write_json(partition, partition_payload("AAA", later))
        decision = self.root / "decision.json"
        payload = {
            "outcomeEvidenceInspected": False,
            "completedBarCutoff": "2026-08-13T09:35:00-04:00",
            "sessionDate": "2026-08-13",
            "sourceHashes": {"minute:AAA": sha256(partition)},
            "candidates": [
                {
                    "symbol": "AAA",
                    "decisionAt": "2026-08-13T09:35:00-04:00",
                    "decisionQuote": {"ask": 10.0},
                    "models": {
                        "fullStructure": {
                            "hypotheticalDecision": "ALLOW",
                            "setupId": "SETUP-A",
                            "stop": 9.5,
                            "targets": [12.0],
                        }
                    },
                }
            ],
        }
        payload["decisionFingerprint"] = packet_fingerprint(payload)
        write_json(decision, payload)

        result = build_outcome_packet(
            decision_path=decision,
            minute_store_root=minute_root,
            output_path=self.root / "outcome.json",
        )

        candidate = result["candidates"][0]
        self.assertEqual("STOP_FIRST", candidate["targetStopSequence"])
        self.assertEqual(4.0, candidate["mfePct"])
        self.assertEqual(-6.0, candidate["maePct"])
        self.assertTrue(candidate["currentMhRejectionAvoidedHypotheticalLoss"])

    def test_module_has_no_runtime_or_broker_imports(self) -> None:
        source = (
            Path(__file__).parents[1] / "momentum_hunter" / "premarket_structure_research.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "alpaca",
            "broker",
            "risk_governor",
            "daily_workflow",
            "scheduler",
            "scoring",
        )
        for value in forbidden:
            self.assertNotIn(f"import {value}", source.lower())
            self.assertNotIn(f"from momentum_hunter.{value}", source.lower())


def structured_windows(symbol: str):
    bars = complete_window(symbol)
    return bars[:-5], bars[-20:-5], bars[-5:]


def complete_window(symbol: str) -> list[ResearchBar]:
    result: list[ResearchBar] = []
    start = datetime(2026, 8, 13, 7, 0, tzinfo=EASTERN)
    for index in range(135):
        timestamp = start + timedelta(minutes=index)
        if timestamp.time() < datetime(2026, 8, 13, 8, 0, tzinfo=EASTERN).time():
            close = 109.5 + (index / 60.0) * 0.5
            high = 110.0 if index == 60 - 1 else close + 0.1
        else:
            close = 109.5 - min((index - 60) * 0.01, 1.0)
            high = close + 0.1
        result.append(
            bar(symbol, timestamp.isoformat(), close - 0.05, high, close - 0.2, close, 100)
        )
    for minute in range(15):
        timestamp = datetime(2026, 8, 13, 9, 15, tzinfo=EASTERN) + timedelta(minutes=minute)
        close = 108.0 + minute * 0.06
        result.append(
            bar(symbol, timestamp.isoformat(), close - 0.03, close + 0.08, 107.5, close, 100)
        )
    opening = [
        ("09:30", 108.8, 109.4, 108.5, 109.3),
        ("09:31", 109.3, 110.0, 109.2, 109.9),
        ("09:32", 109.9, 110.7, 109.8, 110.6),
        ("09:33", 110.6, 111.0, 110.5, 110.95),
        ("09:34", 110.95, 110.99, 110.7, 110.9),
    ]
    for clock, open_price, high, low, close in opening:
        result.append(
            bar(
                symbol,
                f"2026-08-13T{clock}:00-04:00",
                open_price,
                high,
                low,
                close,
                500,
            )
        )
    return sorted(result, key=lambda item: item.timestamp)


def report_payload() -> dict:
    return {
        "metadata": {
            "source_capture_time": "2026-08-13T08:35:01-05:00",
            "source_provider": "finviz",
        },
        "candidates": [candidate_row(symbol, rank) for rank, symbol in enumerate(
            ("CRWV", "NBIS", "IREN", "HPE", "SMCI"), start=1
        )],
    }


def candidate_row(symbol: str, rank: int) -> dict:
    return {
        "rank": rank,
        "symbol": symbol,
        "market_data": {
            "current_bid": 110.95,
            "current_ask": 111.05,
            "spread_percent": 0.09,
        },
        "technical_levels": {
            "previous_day_close": 99.0,
            "previous_day_high": 100.0,
            "previous_day_low": 96.0,
            "atr": 4.0,
        },
        "market_tape": {
            "field_provenance": {
                "current_ask": {
                    "source": "schwab_marketdata_v1_quotes:min_bid_ask_quote_time_v1",
                    "provider_timestamp": "2026-08-13T13:35:38.161000+00:00",
                    "local_receipt_timestamp": "2026-08-13T13:35:38.562310+00:00",
                }
            }
        },
        "trade_plan": {
            "bullish_entry": 100.0,
            "bullish_stop": 96.0,
            "bullish_target_1": 108.0,
            "setup_evidence": {"fingerprint": f"SETUP-{symbol}"},
        },
    }


def partition_payload(symbol: str, bars: list[ResearchBar]) -> dict:
    return {
        "schemaVersion": 1,
        "storeKind": "SCHWAB_INTRADAY_CANDLES",
        "symbol": symbol,
        "sessionDate": "2026-08-13",
        "canonicalSource": CANONICAL_SOURCE,
        "streamSource": "schwab_streamer_chart_equity:v1",
        "legacySourceMixed": False,
        "consumerActivation": {},
        "bars": [stored_bar(item) for item in bars],
    }


def stored_bar(item: ResearchBar) -> dict:
    candle = {
        "symbol": item.symbol,
        "timestamp": item.timestamp.astimezone(timezone.utc).isoformat(),
        "sessionDate": "2026-08-13",
        "open": item.open,
        "high": item.high,
        "low": item.low,
        "close": item.close,
        "volume": item.volume,
        "source": CANONICAL_SOURCE,
        "ohlcvComplete": True,
        "sequence": None,
    }
    return {
        "timestamp": candle["timestamp"],
        "minuteIdentity": f"schwab-equity-1m:v1|{item.symbol}|{candle['timestamp']}",
        "session": "regular" if item.timestamp.time() >= datetime(2026, 8, 13, 9, 30, tzinfo=EASTERN).time() else "extended",
        "state": "HISTORY_ONLY_GAP_FILL",
        "streamVersions": [],
        "historyVersions": [
            {
                "versionId": hashlib.sha256(item.identity.encode()).hexdigest().upper(),
                "source": CANONICAL_SOURCE,
                "firstReceivedAt": "2026-08-13T20:30:00+00:00",
                "candle": candle,
            }
        ],
        "canonicalCandle": candle,
        "discrepancyFields": [],
    }


def bar(
    symbol: str,
    timestamp: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 100,
) -> ResearchBar:
    parsed = datetime.fromisoformat(timestamp).astimezone(EASTERN)
    return ResearchBar(
        symbol=symbol,
        timestamp=parsed,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=CANONICAL_SOURCE,
        state="HISTORY_ONLY_GAP_FILL",
        first_received_at=datetime(2026, 8, 13, 20, 30, tzinfo=timezone.utc),
        identity=f"schwab-equity-1m:v1|{symbol}|{parsed.astimezone(timezone.utc).isoformat()}",
    )


def replace_symbol(item: ResearchBar, symbol: str) -> ResearchBar:
    return ResearchBar(
        symbol=symbol,
        timestamp=item.timestamp,
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=item.volume,
        source=item.source,
        state=item.state,
        first_received_at=item.first_received_at,
        identity=item.identity.replace("|AAA|", f"|{symbol}|"),
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


if __name__ == "__main__":
    unittest.main()
