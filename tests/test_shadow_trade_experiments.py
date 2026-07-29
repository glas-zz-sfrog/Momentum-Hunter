from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_trade_experiments as experiment_module
from momentum_hunter.shadow_market_validity import DecisionCycleStore
from momentum_hunter.shadow_paper_reconciliation import (
    record_paper_money_reconciliation,
)
from momentum_hunter.shadow_trade_experiments import (
    SHADOW_TRADE_EXPERIMENT_MODE,
    ShadowTradeExperimentError,
    generate_shadow_trade_experiment,
)
from momentum_hunter.shadow_trading import (
    ShadowQuote,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingService,
)


class ShadowTradeExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "trade-plan.json"
        self.state_path = self.root / "shadow-state.json"
        self.output_dir = self.root / "experiments"
        self.report_path.write_text(
            json.dumps(_report_payload()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start_trade(self, *, with_cycle: bool = False):
        cycle_id = "cycle-shadow-experiment-1" if with_cycle else ""
        opportunity_id = "opportunity-shadow-experiment-1" if with_cycle else ""
        trade = self.service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="shadow-experiment-command-1",
            decision_at=_at("2026-07-29T09:00:00-05:00"),
            decision_cycle_id=cycle_id,
            opportunity_id=opportunity_id,
            selection_quote_json=(
                json.dumps(
                    _quote_payload(
                        "TEST",
                        "2026-07-29T08:59:55-05:00",
                        9.94,
                        9.95,
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if with_cycle
                else ""
            ),
        )
        if with_cycle:
            self.service.decision_cycle_store.save_cycle(
                _decision_cycle(trade)
            )
            self.service.decision_cycle_store.append_observations(
                (
                    {
                        "symbol": "TEST",
                        "timestamp": "2026-07-29T09:30:00-05:00",
                        "bid": 10.49,
                        "ask": 10.51,
                        "last": 10.50,
                        "source": "synthetic-candidate",
                    },
                    {
                        "symbol": "SPY",
                        "timestamp": "2026-07-29T09:30:00-05:00",
                        "bid": 631.99,
                        "ask": 632.01,
                        "last": 632.0,
                        "source": "synthetic-benchmark",
                    },
                )
            )
        return trade

    def complete_trade(self, *, with_cycle: bool = True):
        trade = self.start_trade(with_cycle=with_cycle)
        self.service.process_quote(
            _quote(
                "2026-07-29T09:00:05-05:00",
                bid=9.94,
                ask=9.95,
                high=9.96,
                low=9.93,
            ),
            received_at=_at("2026-07-29T09:00:05-05:00"),
        )
        self.service.process_quote(
            _quote(
                "2026-07-29T09:30:00-05:00",
                bid=10.55,
                ask=10.56,
                high=10.57,
                low=9.90,
            ),
            received_at=_at("2026-07-29T09:30:00-05:00"),
        )
        completed = self.service.store.load().trades[0]
        if with_cycle:
            self.service.decision_cycle_store.finalize_counterfactuals(
                completed.decision_cycle_id,
                horizon_at=completed.outcome.exit_timestamp,
            )
        return completed

    def generate(self, trade, **overrides):
        values = {
            "shadow_trade_id": trade.shadow_trade_id,
            "state_path": self.state_path,
            "output_dir": self.output_dir,
        }
        values.update(overrides)
        return generate_shadow_trade_experiment(**values)

    def test_pending_trade_report_is_honest_read_only_and_idempotent(
        self,
    ) -> None:
        trade = self.start_trade()
        state_before = self.state_path.read_bytes()
        source_before = self.report_path.read_bytes()

        first = self.generate(trade)
        repeated = self.generate(trade)

        self.assertTrue(first.created)
        self.assertFalse(repeated.created)
        self.assertEqual(first.experiment_id, repeated.experiment_id)
        self.assertTrue(first.source_state_unchanged)
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(source_before, self.report_path.read_bytes())
        payload = _experiment(first.json_path)
        self.assertEqual(
            "PENDING_OR_UNFILLED",
            payload["artifact_status"],
        )
        self.assertEqual(
            "NOT_APPLICABLE",
            payload["selection_experiment"]["evidence_status"],
        )
        self.assertEqual("PASS", payload["integrity"]["status"])
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["broker_request_performed"])
        self.assertFalse(payload["order_action_performed"])
        self.assertFalse(
            payload["research_limits"][
                "single_trade_strategy_conclusion_authorized"
            ]
        )
        self.assertFalse(
            payload["research_limits"]["trading_authorized"]
        )

    def test_complete_report_links_cycle_counterfactuals_and_outcome(
        self,
    ) -> None:
        trade = self.complete_trade()
        state_before = self.state_path.read_bytes()
        cycles_before = (
            self.service.decision_cycle_store.path.read_bytes()
        )

        result = self.generate(trade)

        payload = _experiment(result.json_path)
        self.assertEqual("COMPLETE", payload["artifact_status"])
        self.assertEqual("PASS", payload["integrity"]["status"])
        self.assertEqual(
            "PASS",
            payload["selection_experiment"]["evidence_status"],
        )
        self.assertEqual(
            "FINALIZED_TO_SELECTED_TRADE_EXIT",
            payload["selection_experiment"]["counterfactual_status"],
        )
        marks = {
            item["symbol"]: item
            for item in payload["selection_experiment"][
                "counterfactual_marks"
            ]
        }
        self.assertEqual({"SPY", "TEST"}, set(marks))
        self.assertTrue(marks["SPY"]["available"])
        self.assertTrue(marks["TEST"]["available"])
        self.assertEqual("WIN", payload["outcome"]["classification"])
        self.assertGreater(payload["outcome"]["executable_pnl"], 0)
        self.assertGreater(payload["outcome"]["mfe_dollars"], 0)
        self.assertLess(payload["outcome"]["mae_dollars"], 0)
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(
            cycles_before,
            self.service.decision_cycle_store.path.read_bytes(),
        )
        markdown = result.markdown_path.read_text(encoding="utf-8")
        self.assertIn("Single-trade strategy conclusion authorized: no", markdown)
        self.assertIn("| SPY | BENCHMARK |", markdown)

    def test_optional_paper_reconciliation_records_model_delta_only(
        self,
    ) -> None:
        trade = self.complete_trade()
        reconciliation_dir = self.root / "paper-reconciliations"
        reconciliation = record_paper_money_reconciliation(
            state_path=self.state_path,
            output_dir=reconciliation_dir,
            shadow_trade_id=trade.shadow_trade_id,
            exact_ticket_entered=(
                "BUY 2 TEST LIMIT 10.00 DAY REGULAR in thinkorswim paperMoney"
            ),
            paper_money_result="FILLED",
            paper_money_fill_price=9.96,
            paper_money_exit_price=10.53,
            operator_modifications="None",
            paper_money_exit="Manual target exit.",
            paper_money_outcome="CLOSED_WIN",
            reconciliation_notes="Synthetic model comparison.",
            recorded_at=_at("2026-07-29T09:31:00-05:00"),
        )
        reconciliation_before = reconciliation.path.read_bytes()

        result = self.generate(
            trade,
            paper_reconciliation_path=reconciliation.path,
        )

        payload = _experiment(result.json_path)
        paper = payload["paper_money_reconciliation"]
        self.assertEqual("PASS", paper["evidence_status"])
        self.assertEqual(
            "FULL_LIFECYCLE_COMPARISON",
            paper["comparison_status"],
        )
        self.assertIsNotNone(
            paper["paper_minus_fake_executable_pnl"]
        )
        self.assertNotIn("exact_ticket_entered", paper)
        self.assertEqual(
            reconciliation_before,
            reconciliation.path.read_bytes(),
        )

    def test_missing_linked_decision_cycle_is_recorded_as_invalid(
        self,
    ) -> None:
        trade = self.start_trade(with_cycle=True)
        self.service.decision_cycle_store.path.unlink()

        result = self.generate(trade)

        payload = _experiment(result.json_path)
        self.assertEqual("EVIDENCE_INVALID", payload["artifact_status"])
        self.assertEqual("FAIL", payload["integrity"]["status"])
        self.assertEqual(
            "MISSING",
            payload["selection_experiment"]["evidence_status"],
        )
        self.assertTrue(
            any(
                item["source"] == "decision_cycle"
                for item in payload["integrity"]["findings"]
            )
        )

    def test_mismatched_decision_cycle_fails_integrity(self) -> None:
        trade = self.start_trade(with_cycle=True)
        cycle = self.service.decision_cycle_store.get(
            trade.decision_cycle_id
        )
        assert cycle is not None
        self.service.decision_cycle_store.save_cycle(
            {**cycle, "selected_symbol": "WRONG"}
        )

        result = self.generate(trade)

        payload = _experiment(result.json_path)
        self.assertEqual("FAIL", payload["integrity"]["status"])
        self.assertTrue(
            any(
                item["field"] == "selected_symbol"
                for item in payload["integrity"]["findings"]
            )
        )

    def test_duplicate_linked_decision_cycle_fails_closed(self) -> None:
        trade = self.start_trade(with_cycle=True)
        cycle_path = self.service.decision_cycle_store.path
        payload = json.loads(cycle_path.read_text(encoding="utf-8"))
        payload["cycles"].append(payload["cycles"][0])
        cycle_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "duplicate linked cycle",
        ):
            self.generate(trade)

    def test_missing_and_duplicate_trade_ids_fail_closed(self) -> None:
        trade = self.start_trade()
        with self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "exactly one",
        ):
            generate_shadow_trade_experiment(
                shadow_trade_id="missing-trade",
                state_path=self.state_path,
                output_dir=self.output_dir,
            )

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["trades"].append(payload["trades"][0])
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(
            (ShadowTradeExperimentError, ShadowStateError, ValueError)
        ):
            self.generate(trade)

    def test_conflicting_existing_artifact_fails_closed(self) -> None:
        trade = self.start_trade()
        result = self.generate(trade)
        result.markdown_path.write_text(
            "tampered\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "conflicts",
        ):
            self.generate(trade)

    def test_explicit_missing_reconciliation_fails_closed(self) -> None:
        trade = self.start_trade()
        with self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "does not exist",
        ):
            self.generate(
                trade,
                paper_reconciliation_path=self.root / "missing.json",
            )

    def test_concurrent_source_change_is_detected_after_write(self) -> None:
        trade = self.start_trade()
        original_write = experiment_module.write_shadow_trade_experiment

        def mutate_after_write(experiment, *, output_dir):
            result = original_write(experiment, output_dir=output_dir)
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            payload["updated_at"] = "2026-07-29T09:01:00-05:00"
            self.state_path.write_text(json.dumps(payload), encoding="utf-8")
            return result

        with patch.object(
            experiment_module,
            "write_shadow_trade_experiment",
            side_effect=mutate_after_write,
        ), self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "changed while building",
        ):
            self.generate(trade)

    def test_module_has_no_provider_broker_or_production_scoring_surface(
        self,
    ) -> None:
        source = Path(experiment_module.__file__).read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
        forbidden_import_fragments = {
            "schwab",
            "market_data",
            "scoring",
            "readiness",
            "alerts",
            "engine_host",
            "shadow_selection",
        }
        self.assertFalse(
            {
                name
                for name in imports
                if any(
                    fragment in name
                    for fragment in forbidden_import_fragments
                )
            }
        )
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertIn(SHADOW_TRADE_EXPERIMENT_MODE, source)


def _experiment(path: Path) -> dict:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    experiment = envelope["experiment"]
    expected = hashlib.sha256(
        json.dumps(
            experiment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    if envelope["experiment_sha256"] != expected:
        raise AssertionError("Experiment envelope hash does not match.")
    return experiment


def _decision_cycle(trade) -> dict:
    selection_quote = _quote_payload(
        "TEST",
        "2026-07-29T08:59:55-05:00",
        9.94,
        9.95,
    )
    benchmark_quote = _quote_payload(
        "SPY",
        "2026-07-29T08:59:55-05:00",
        629.99,
        630.01,
    )
    return {
        "cycle_id": trade.decision_cycle_id,
        "decision_at": trade.decision_timestamp,
        "updated_at": trade.decision_timestamp,
        "status": "TRADE_STARTED",
        "reason": "Synthetic eligible candidate selected.",
        "report_sha256": trade.evidence.source_sha256,
        "shadow_trade_id": trade.shadow_trade_id,
        "opportunity_id": trade.opportunity_id,
        "selected_symbol": trade.symbol,
        "candidate_assessments": [
            {
                "symbol": "TEST",
                "rank": 1,
                "eligible": True,
                "reasons": [],
                "quote": selection_quote,
            }
        ],
        "deterministic_random_eligible": {
            "symbol": "TEST",
            "rank": 1,
        },
        "benchmark_symbols": ["SPY"],
        "benchmark_baselines": {"SPY": benchmark_quote},
        "market_observations": [],
        "counterfactual_marks": [],
    }


def _report_payload() -> dict:
    row = {
        "rank": 1,
        "symbol": "TEST",
        "company": "Synthetic Test Corporation",
        "market_data": {
            "last_price": 9.9,
            "current_bid": 9.89,
            "current_ask": 9.91,
            "spread_percent": 0.2,
            "relative_volume": 2.0,
        },
        "scoring": {
            "composite_score": 91,
            "catalyst_summary": "Synthetic catalyst",
            "catalyst_cluster": "Synthetic setup",
        },
        "trade_plan": {
            "bullish_entry": 10.0,
            "bullish_stop": 9.5,
            "bullish_target_1": 10.5,
            "bullish_target_2": 11.0,
            "risk_reward_ratio": 1.0,
            "estimated_shares_for_500": 2.0,
            "estimated_dollar_risk": 1.0,
            "estimated_target_1_reward": 1.0,
            "confidence": "MEDIUM",
            "tradeability": "MEDIUM",
            "readiness": "EXECUTION_READY_TRADE",
            "blocking_reasons": [],
            "warnings": [],
        },
        "opportunity_notes": ["Synthetic test row"],
    }
    return {
        "schema_version": 1,
        "metadata": {
            "generated_at": "2026-07-29T08:59:00-05:00",
            "source_capture_path": "synthetic/capture.json",
            "source_capture_time": "2026-07-29T08:58:00-05:00",
            "source_provider": "synthetic-test-provider",
            "source_scanner": "Institutional Momentum",
            "market_regime": "risk_on",
        },
        "top_5_for_capital": [row],
        "candidates": [row],
    }


def _quote(
    timestamp: str,
    *,
    bid: float,
    ask: float,
    high: float,
    low: float,
) -> ShadowQuote:
    return ShadowQuote(
        symbol="TEST",
        timestamp=timestamp,
        bid=bid,
        ask=ask,
        last=bid,
        high=high,
        low=low,
        session="regular",
        trading_state="tradable",
        source="synthetic-test",
    )


def _quote_payload(
    symbol: str,
    timestamp: str,
    bid: float,
    ask: float,
) -> dict:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "bid": bid,
        "ask": ask,
        "last": bid,
        "session": "regular",
        "trading_state": "tradable",
        "source": "synthetic-test",
    }


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
