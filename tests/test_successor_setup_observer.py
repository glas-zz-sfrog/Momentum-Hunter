from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.premarket_structure_research import CANONICAL_SOURCE, EASTERN, ResearchBar
from momentum_hunter.successor_setup_observer import (
    ALLOW_AT_DECISION,
    AMBIGUOUS_SAME_BAR,
    EXECUTION_AUTHORITY,
    POLICY_FINGERPRINT,
    SAMPLE_ID,
    SuccessorSetupResearchError,
    build_dormant_activation_plan,
    build_pass_one,
    build_pass_two,
    build_sample_summary,
    create_sample_charter,
    packet_fingerprint,
)


class SuccessorSetupObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / (
            f"_test-successor-observer-{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=True)
        self.charter = self.root / "charter.json"
        create_sample_charter(
            created_at="2026-08-13T18:00:00-04:00", output_path=self.charter
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_charter_starts_empty_and_excludes_setup001(self) -> None:
        payload = json.loads(self.charter.read_text(encoding="utf-8"))

        self.assertEqual(SAMPLE_ID, payload["sampleId"])
        self.assertEqual(POLICY_FINGERPRINT, payload["policyFingerprint"])
        self.assertEqual(
            "CASE_STUDY_EXCLUDED_FROM_PROSPECTIVE_DENOMINATOR",
            payload["setup001Treatment"],
        )
        self.assertTrue(all(value == 0 for value in payload["initialCounts"].values()))
        self.assertEqual(payload["charterFingerprint"], packet_fingerprint(payload))

    def test_pass_one_preserves_denominator_and_provider_bound(self) -> None:
        paths = self._evidence(symbols=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"))

        result = self._pass_one(paths)

        self.assertEqual(6, result["candidateDenominatorCount"])
        self.assertEqual(5, result["evaluatedCandidateCount"])
        self.assertEqual(
            "NOT_EVALUATED_PROVIDER_BOUND", result["candidates"][5]["evaluationStatus"]
        )
        self.assertEqual("ABSTAIN", result["candidates"][5]["researchOpinion"]["decision"])
        self.assertFalse(result["outcomeEvidenceInspected"])
        self.assertEqual("NONE", result["executionAuthority"])

    def test_outcome_bar_does_not_leak_into_pass_one(self) -> None:
        paths = self._evidence(symbols=("AAA",), later=[bar("AAA", "2026-08-13T10:00:00-04:00", 500, 999, 1, 900)])
        before_sources = {path: sha256(path) for path in paths["source_paths"]}
        first = self._pass_one(paths, output=self.root / "first.json")
        self.assertEqual(before_sources, {path: sha256(path) for path in paths["source_paths"]})
        rewrite_partition(
            paths["minute"] / "2026-08-13" / "AAA.json",
            complete_window("AAA") + [bar("AAA", "2026-08-13T10:00:00-04:00", 20, 21, 19, 20)],
        )
        second = self._pass_one(paths, output=self.root / "second.json")

        self.assertEqual(first, second)
        self.assertLess(first["candidates"][0]["premarket"]["high"], 500)
        self.assertLess(first["candidates"][0]["openingRange"]["high"], 500)
        self.assertNotIn("postCutoffBarsExcluded", first["candidates"][0]["sourceEvidence"])
        self.assertNotEqual(
            before_sources[paths["minute"] / "2026-08-13" / "AAA.json"],
            sha256(paths["minute"] / "2026-08-13" / "AAA.json"),
        )
        for path in (paths["report"], paths["capture"], self.charter):
            self.assertEqual(before_sources[path], sha256(path))

    def test_candidate_is_not_omitted_because_later_bar_loses(self) -> None:
        paths = self._evidence(
            symbols=("AAA",), later=[bar("AAA", "2026-08-13T09:35:00-04:00", 111, 111.1, 1, 2)]
        )

        result = self._pass_one(paths)

        self.assertEqual(["AAA"], [item["symbol"] for item in result["candidates"]])
        self.assertEqual(1, result["candidateDenominatorCount"])

    def test_missing_opening_bar_abstains_without_dropping_candidate(self) -> None:
        paths = self._evidence(symbols=("AAA",), transform=lambda values: values[:-1])

        result = self._pass_one(paths)

        self.assertEqual("INSUFFICIENT_OPENING_STRUCTURE_EVIDENCE", result["candidates"][0]["evaluationStatus"])
        self.assertEqual("ABSTAIN", result["candidates"][0]["researchOpinion"]["decision"])

    def test_missing_premarket_history_abstains(self) -> None:
        paths = self._evidence(
            symbols=("AAA",), transform=lambda values: [item for item in values if item.timestamp.time() >= datetime(2026, 8, 13, 9, 30, tzinfo=EASTERN).time()]
        )

        result = self._pass_one(paths)

        self.assertEqual("INSUFFICIENT_PREMARKET_HISTORY", result["candidates"][0]["evaluationStatus"])

    def test_wrong_session_date_is_rejected_as_evidence_failure(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        partition = paths["minute"] / "2026-08-13" / "AAA.json"
        payload = json.loads(partition.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["timestamp"] = "2026-08-14T11:00:00+00:00"
        payload["bars"][0]["historyVersions"][-1]["candle"] = dict(payload["bars"][0]["canonicalCandle"])
        payload["bars"][0]["timestamp"] = "2026-08-14T11:00:00+00:00"
        payload["bars"][0]["minuteIdentity"] = "schwab-equity-1m:v1|AAA|2026-08-14T11:00:00+00:00"
        write_json(partition, payload)

        result = self._pass_one(paths)

        self.assertEqual("INSUFFICIENT_PREMARKET_HISTORY", result["candidates"][0]["evaluationStatus"])
        self.assertIn("session", result["candidates"][0]["evidenceFailure"].lower())

    def test_wrong_symbol_and_tampered_identity_are_not_trusted(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        partition = paths["minute"] / "2026-08-13" / "AAA.json"
        payload = json.loads(partition.read_text(encoding="utf-8"))
        payload["symbol"] = "WRONG"
        write_json(partition, payload)

        result = self._pass_one(paths)

        self.assertEqual("INSUFFICIENT_PREMARKET_HISTORY", result["candidates"][0]["evaluationStatus"])
        self.assertIn("symbol mismatch", result["candidates"][0]["evidenceFailure"].lower())

    def test_pass_one_proposes_distinct_successor_without_rewriting_original(self) -> None:
        paths = self._evidence(symbols=("AAA",))

        result = self._pass_one(paths)
        candidate = result["candidates"][0]

        self.assertEqual("ORIGINAL_MISSED", candidate["originalSetup"]["lifecycleStatus"])
        self.assertEqual("CONTINUATION_BREAKOUT", candidate["successorSetup"]["family"])
        self.assertNotEqual(
            candidate["originalSetup"]["setupFingerprint"],
            candidate["successorSetup"]["setupId"],
        )
        self.assertEqual(ALLOW_AT_DECISION, candidate["researchOpinion"]["decision"])
        self.assertTrue(candidate["originalSetup"]["immutableOriginal"])

    def test_later_rally_does_not_change_frozen_block(self) -> None:
        paths = self._evidence(symbols=("AAA",), ask=120.0)
        decision = self._pass_one(paths)
        frozen = decision["candidates"][0]["researchOpinion"]
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [
                bar("AAA", "2026-08-13T10:00:00-04:00", 120, 150, 119, 149),
                bar("AAA", "2026-08-13T15:55:00-04:00", 149, 151, 148, 150),
            ],
        )

        outcome = build_pass_two(
            decision_path=self.root / "decision.json",
            minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00",
            output_path=self.root / "outcome.json",
        )

        self.assertEqual("BLOCK", frozen["decision"])
        self.assertEqual("NO_HYPOTHETICAL_TRADE", outcome["candidates"][0]["outcomeStatus"])
        self.assertTrue(outcome["candidates"][0]["postDecisionObservation"]["laterBehaviorCannotAlterPass1"])

    def test_same_bar_stop_and_target_is_ambiguous(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        decision = self._pass_one(paths)
        setup = decision["candidates"][0]["successorSetup"]
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [
                bar(
                    "AAA",
                    "2026-08-13T09:35:00-04:00",
                    setup["trigger"],
                    setup["targets"][0] + 0.1,
                    setup["stop"] - 0.1,
                    setup["trigger"],
                )
            ],
        )

        result = build_pass_two(
            decision_path=self.root / "decision.json",
            minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00",
            output_path=self.root / "outcome.json",
        )

        self.assertEqual(AMBIGUOUS_SAME_BAR, result["candidates"][0]["outcomeStatus"])
        self.assertTrue(result["candidates"][0]["excursionWindowEndsAtTerminal"])
        self.assertIsNone(result["candidates"][0]["mfe"])
        self.assertIsNone(result["candidates"][0]["mae"])

    def test_pending_successor_can_remain_untriggered(self) -> None:
        paths = self._evidence(symbols=("AAA",), ask=110.95)
        decision = self._pass_one(paths)
        self.assertEqual("ALLOW_PENDING_TRIGGER", decision["candidates"][0]["researchOpinion"]["decision"])
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [
                bar("AAA", "2026-08-13T09:35:00-04:00", 110.8, 110.99, 110.6, 110.9),
                bar("AAA", "2026-08-13T15:55:00-04:00", 110.8, 110.99, 110.6, 110.9),
            ],
        )

        result = self._pass_two(paths)

        self.assertEqual("UNTRIGGERED", result["candidates"][0]["outcomeStatus"])
        self.assertFalse(result["candidates"][0]["hypotheticalTrade"])

    def test_pending_successor_partial_horizon_is_data_failure(self) -> None:
        paths = self._evidence(symbols=("AAA",), ask=110.95)
        self._pass_one(paths)
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T10:00:00-04:00", 110.8, 110.99, 110.6, 110.9)],
        )

        result = self._pass_two(paths)

        self.assertEqual("DATA_FAILURE", result["candidates"][0]["outcomeStatus"])
        self.assertEqual(
            "INCOMPLETE_OUTCOME_HORIZON_BEFORE_15_55_ET",
            result["candidates"][0]["reason"],
        )

    def test_pending_successor_can_be_invalidated_before_trigger(self) -> None:
        paths = self._evidence(symbols=("AAA",), ask=110.95)
        decision = self._pass_one(paths)
        setup = decision["candidates"][0]["successorSetup"]
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T09:35:00-04:00", 110.0, 110.9, setup["stop"] - 0.1, 109.0)],
        )

        result = self._pass_two(paths)

        self.assertEqual("INVALIDATED", result["candidates"][0]["outcomeStatus"])
        self.assertFalse(result["candidates"][0]["hypotheticalTrade"])

    def test_triggered_successor_times_out_without_stop_or_target(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        decision = self._pass_one(paths)
        setup = decision["candidates"][0]["successorSetup"]
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T15:55:00-04:00", 111.1, setup["targets"][0] - 0.1, setup["stop"] + 0.1, 112.0)],
        )

        result = self._pass_two(paths)

        self.assertEqual("TIMEOUT", result["candidates"][0]["outcomeStatus"])
        self.assertEqual("2026-08-13T15:55:00-04:00", result["candidates"][0]["terminalAt"])

    def test_pass_two_rejects_before_close_and_partial_horizon_is_data_failure(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        self._pass_one(paths)
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T10:00:00-04:00", 111.0, 111.4, 110.5, 111.1)],
        )

        with self.assertRaises(SuccessorSetupResearchError):
            build_pass_two(
                decision_path=self.root / "decision.json",
                minute_store_root=paths["minute"],
                finalized_at="2026-08-13T15:59:59-04:00",
                output_path=self.root / "too-early.json",
            )
        result = self._pass_two(paths)
        self.assertEqual("DATA_FAILURE", result["candidates"][0]["outcomeStatus"])
        self.assertEqual(
            "INCOMPLETE_OUTCOME_HORIZON_BEFORE_15_55_ET",
            result["candidates"][0]["reason"],
        )

    def test_stop_ends_excursion_before_later_rally(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        decision = self._pass_one(paths)
        setup = decision["candidates"][0]["successorSetup"]
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [
                bar("AAA", "2026-08-13T09:35:00-04:00", 111.0, 111.5, setup["stop"] - 0.1, 109.0),
                bar("AAA", "2026-08-13T09:36:00-04:00", 109.0, 999.0, 1.0, 900.0),
            ],
        )

        result = self._pass_two(paths)
        candidate = result["candidates"][0]

        self.assertEqual("STOP_FIRST", candidate["outcomeStatus"])
        self.assertLess(candidate["mfe"], 1.0)
        self.assertEqual("2026-08-13T09:35:00-04:00", candidate["terminalAt"])

    def test_paper_baseline_is_sanitized_to_decision_fields(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        paper = self.root / "paper.json"
        write_json(
            paper,
            {
                "decision": {
                    "classification": "NO_TRADE",
                    "accountNumber": "SECRET_ACCOUNT",
                    "buyingPower": 100000,
                    "candidateEvaluations": [
                        {"symbol": "AAA", "eligible": False, "blockers": ["MISSED_ENTRY"]}
                    ],
                }
            },
        )

        result = build_pass_one(
            charter_path=self.charter,
            trade_plan_path=paths["report"],
            capture_path=paths["capture"],
            minute_store_root=paths["minute"],
            observed_at="2026-08-13T09:36:00-04:00",
            paper_result_path=paper,
            output_path=self.root / "decision.json",
        )

        encoded = json.dumps(result)
        self.assertNotIn("SECRET_ACCOUNT", encoded)
        self.assertNotIn("accountNumber", recursive_keys(result))
        self.assertNotIn("buyingPower", recursive_keys(result))
        self.assertTrue(result["candidates"][0]["baseline"]["paperEvaluated"])

    def test_pass_two_rejects_altered_pass_one(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        self._pass_one(paths)
        payload = json.loads((self.root / "decision.json").read_text(encoding="utf-8"))
        payload["candidates"][0]["rank"] = 99
        write_json(self.root / "decision.json", payload)

        with self.assertRaises(SuccessorSetupResearchError):
            build_pass_two(
                decision_path=self.root / "decision.json",
                minute_store_root=paths["minute"],
                finalized_at="2026-08-13T16:05:00-04:00",
                output_path=self.root / "outcome.json",
            )

    def test_pass_two_rejects_changed_cutoff_evidence(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        self._pass_one(paths)
        partition = paths["minute"] / "2026-08-13" / "AAA.json"
        payload = json.loads(partition.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["close"] += 0.01
        payload["bars"][0]["historyVersions"][-1]["candle"] = dict(payload["bars"][0]["canonicalCandle"])
        write_json(partition, payload)

        result = build_pass_two(
            decision_path=self.root / "decision.json",
            minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00",
            output_path=self.root / "outcome.json",
        )

        self.assertEqual("DATA_FAILURE", result["candidates"][0]["outcomeStatus"])
        self.assertIn("changed after Pass 1", result["candidates"][0]["failure"])

    def test_duplicate_pass_one_is_idempotent_and_conflict_fails_closed(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        first = self._pass_one(paths)
        output_hash = sha256(self.root / "decision.json")

        second = self._pass_one(paths)
        self.assertEqual(first, second)
        self.assertEqual(output_hash, sha256(self.root / "decision.json"))
        conflicting = dict(first)
        conflicting["decisionFingerprint"] = "ALTERED"
        write_json(self.root / "decision.json", conflicting)
        with self.assertRaises(SuccessorSetupResearchError):
            self._pass_one(paths)

    def test_duplicate_pass_two_is_idempotent_and_conflict_fails_closed(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        self._pass_one(paths)
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T09:35:00-04:00", 111, 111.2, 110.9, 111.1)],
        )
        output = self.root / "outcome.json"
        first = build_pass_two(
            decision_path=self.root / "decision.json", minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00", output_path=output
        )
        output_hash = sha256(output)
        second = build_pass_two(
            decision_path=self.root / "decision.json", minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00", output_path=output
        )
        self.assertEqual(first, second)
        self.assertEqual(output_hash, sha256(output))
        payload = dict(first)
        payload["outcomeFingerprint"] = "ALTERED"
        write_json(output, payload)
        with self.assertRaises(SuccessorSetupResearchError):
            build_pass_two(
                decision_path=self.root / "decision.json", minute_store_root=paths["minute"],
                finalized_at="2026-08-13T16:05:00-04:00", output_path=output
            )

    def test_summary_counts_prospective_packets_only(self) -> None:
        paths = self._evidence(symbols=("AAA",))
        self._pass_one(paths)
        append_bars(
            paths["minute"] / "2026-08-13" / "AAA.json",
            [bar("AAA", "2026-08-13T09:35:00-04:00", 111, 116.1, 110.9, 116.0)],
        )
        build_pass_two(
            decision_path=self.root / "decision.json",
            minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00",
            output_path=self.root / "outcome.json",
        )

        summary = build_sample_summary(
            charter_path=self.charter,
            pass_one_paths=[self.root / "decision.json"],
            pass_two_paths=[self.root / "outcome.json"],
            output_path=self.root / "summary.json",
        )

        self.assertEqual(1, summary["counts"]["tradingSessionsObserved"])
        self.assertEqual(1, summary["counts"]["openingCandidatesObserved"])
        self.assertEqual(1, summary["counts"]["successorSetupsProposed"])
        self.assertEqual("NO_EDGE_CLAIM_NO_PARAMETER_TUNING", summary["interpretation"])

    def test_dormant_plan_cannot_affect_opening_or_paper(self) -> None:
        plan = build_dormant_activation_plan(
            created_at="2026-08-13T18:01:00-04:00", output_path=self.root / "dormant.json"
        )

        self.assertEqual("NOT_INSTALLED", plan["status"])
        self.assertFalse(plan["activationAuthorized"])
        self.assertEqual("NONE", plan["executionAuthority"])
        self.assertIn("CANNOT_CHANGE_OPENING_OR_PAPER_STATUS", plan["failureIsolation"])

    def test_module_has_no_network_broker_service_or_scheduler_capability(self) -> None:
        source = (
            Path(__file__).parents[1] / "momentum_hunter" / "successor_setup_observer.py"
        ).read_text(encoding="utf-8").lower()
        forbidden_imports = (
            "requests",
            "urllib",
            "httpx",
            "websocket",
            "alpaca",
            "broker",
            "risk_governor",
            "daily_workflow",
            "scheduling",
            "automation_service",
        )
        for value in forbidden_imports:
            self.assertNotIn(f"import {value}", source)
            self.assertNotIn(f"from momentum_hunter.{value}", source)
        self.assertNotIn("submit_order(", source)
        self.assertNotIn("cancel_order(", source)

    def _evidence(
        self,
        *,
        symbols: tuple[str, ...],
        later: list[ResearchBar] | None = None,
        transform=None,
        ask: float = 111.05,
    ) -> dict:
        report = self.root / "trade-plan.json"
        capture = self.root / "capture.json"
        minute = self.root / "minute"
        write_json(report, report_payload(symbols, ask=ask))
        write_json(capture, {"status": "CAPTURED", "market_regime": "PRESERVED"})
        for symbol in symbols[:5]:
            values = complete_window(symbol)
            if transform:
                values = transform(values)
            if later:
                values += [replace_symbol(item, symbol) for item in later]
            rewrite_partition(minute / "2026-08-13" / f"{symbol}.json", values)
        for benchmark in ("SPY", "QQQ", "IWM"):
            rewrite_partition(minute / "2026-08-13" / f"{benchmark}.json", complete_window(benchmark))
        return {
            "report": report,
            "capture": capture,
            "minute": minute,
            "source_paths": [report, capture, self.charter]
            + sorted((minute / "2026-08-13").glob("*.json")),
        }

    def _pass_one(self, paths: dict, output: Path | None = None) -> dict:
        return build_pass_one(
            charter_path=self.charter,
            trade_plan_path=paths["report"],
            capture_path=paths["capture"],
            minute_store_root=paths["minute"],
            observed_at="2026-08-13T09:36:00-04:00",
            output_path=output or self.root / "decision.json",
        )

    def _pass_two(self, paths: dict) -> dict:
        return build_pass_two(
            decision_path=self.root / "decision.json",
            minute_store_root=paths["minute"],
            finalized_at="2026-08-13T16:05:00-04:00",
            output_path=self.root / "outcome.json",
        )


def complete_window(symbol: str) -> list[ResearchBar]:
    result: list[ResearchBar] = []
    start = datetime(2026, 8, 13, 7, 0, tzinfo=EASTERN)
    for index in range(135):
        timestamp = start + timedelta(minutes=index)
        if index < 60:
            close = 109.5 + (index / 60.0) * 0.5
            high = 110.0 if index == 59 else close + 0.1
        else:
            close = 109.5 - min((index - 60) * 0.01, 1.0)
            high = close + 0.1
        result.append(bar(symbol, timestamp.isoformat(), close - 0.05, high, close - 0.2, close))
    for minute in range(15):
        timestamp = datetime(2026, 8, 13, 9, 15, tzinfo=EASTERN) + timedelta(minutes=minute)
        close = 108.0 + minute * 0.06
        result.append(bar(symbol, timestamp.isoformat(), close - 0.03, close + 0.08, 107.5, close))
    opening = [
        ("09:30", 108.8, 109.4, 108.5, 109.3),
        ("09:31", 109.3, 110.0, 109.2, 109.9),
        ("09:32", 109.9, 110.7, 109.8, 110.6),
        ("09:33", 110.6, 111.0, 110.5, 110.95),
        ("09:34", 110.95, 110.99, 110.7, 110.9),
    ]
    for clock, open_price, high, low, close in opening:
        result.append(bar(symbol, f"2026-08-13T{clock}:00-04:00", open_price, high, low, close, 500))
    return sorted(result, key=lambda item: item.timestamp)


def report_payload(symbols: tuple[str, ...], *, ask: float) -> dict:
    return {
        "metadata": {
            "source_capture_time": "2026-08-13T08:35:01-05:00",
            "source_provider": "finviz",
        },
        "candidates": [candidate_row(symbol, rank, ask=ask) for rank, symbol in enumerate(symbols, 1)],
    }


def candidate_row(symbol: str, rank: int, *, ask: float) -> dict:
    return {
        "rank": rank,
        "symbol": symbol,
        "market_data": {"current_bid": ask - 0.1, "current_ask": ask, "spread_percent": 0.09},
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
            "blocking_reasons": ["DO_NOT_TRADE_MISSED_ENTRY"],
            "setup_evidence": {"fingerprint": f"SETUP-{symbol}"},
        },
    }


def rewrite_partition(path: Path, bars: list[ResearchBar]) -> None:
    payload = {
        "schemaVersion": 1,
        "storeKind": "SCHWAB_INTRADAY_CANDLES",
        "symbol": bars[0].symbol,
        "sessionDate": "2026-08-13",
        "canonicalSource": CANONICAL_SOURCE,
        "streamSource": "schwab_streamer_chart_equity:v1",
        "legacySourceMixed": False,
        "adjustmentBasis": "PROVIDER_RETURNED_UNSPECIFIED_ADJUSTMENT",
        "consumerActivation": {},
        "bars": [stored_bar(item) for item in sorted(bars, key=lambda value: value.timestamp)],
    }
    write_json(path, payload)


def append_bars(path: Path, bars: list[ResearchBar]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bars"].extend(stored_bar(item) for item in bars)
    payload["bars"].sort(key=lambda item: item["timestamp"])
    write_json(path, payload)


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
        identity=item.identity.replace(f"|{item.symbol}|", f"|{symbol}|"),
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def recursive_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(recursive_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(recursive_keys(item) for item in value)) if value else set()
    return set()


if __name__ == "__main__":
    unittest.main()
