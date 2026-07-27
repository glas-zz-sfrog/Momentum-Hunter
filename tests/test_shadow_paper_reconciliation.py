from __future__ import annotations

import ast
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_paper_reconciliation as reconciliation_module
from momentum_hunter.shadow_paper_reconciliation import (
    PAPER_RECONCILIATION_MODE,
    main,
    record_paper_money_reconciliation,
)
from momentum_hunter.shadow_trading import (
    ShadowStateStore,
    ShadowTradingService,
    shadow_state_to_dict,
)


class PaperMoneyReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "trade-plan.json"
        self.state_path = self.root / "shadow-state.json"
        self.output_dir = self.root / "paper-reconciliations"
        self.report_path.write_text(
            json.dumps(_report_payload()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
        )
        self.trade = self.service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="paper-reconciliation-test",
            decision_at=datetime.fromisoformat("2026-07-27T10:00:00-05:00"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, **overrides):
        values = {
            "state_path": self.state_path,
            "output_dir": self.output_dir,
            "shadow_trade_id": self.trade.shadow_trade_id,
            "exact_ticket_entered": (
                "BUY 2 TEST LIMIT 10.00 DAY REGULAR in thinkorswim paperMoney"
            ),
            "paper_money_result": "FILLED",
            "paper_money_fill_price": 9.99,
            "operator_modifications": "None",
            "paper_money_outcome": "OPEN",
            "reconciliation_notes": "Manual paperMoney entry matched the frozen ticket.",
            "recorded_at": datetime.fromisoformat("2026-07-27T10:05:00-05:00"),
        }
        values.update(overrides)
        return record_paper_money_reconciliation(**values)

    def test_record_is_write_once_nontransmitting_and_preserves_source_state(self) -> None:
        before = self.state_path.read_bytes()
        before_hash = hashlib.sha256(before).hexdigest()

        result = self.record()

        self.assertTrue(result.created)
        self.assertTrue(result.source_state_unchanged)
        self.assertEqual(before, self.state_path.read_bytes())
        payload = json.loads(result.path.read_text(encoding="utf-8"))
        record = payload["reconciliation"]
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(PAPER_RECONCILIATION_MODE, record["mode"])
        self.assertFalse(record["transmitting"])
        self.assertFalse(record["broker_request_performed"])
        self.assertFalse(record["order_action_performed"])
        self.assertEqual(before_hash, record["source_state_sha256"])
        self.assertEqual(self.trade.shadow_trade_id, record["shadow_trade_id"])
        self.assertEqual(self.trade.order.order_id, record["shadow_order_id"])
        self.assertEqual(self.trade.trade_plan_id, record["trade_plan_id"])
        self.assertEqual(
            self.trade.evidence_snapshot_id,
            record["evidence_snapshot_id"],
        )
        self.assertEqual(self.trade.plan_fingerprint, record["plan_fingerprint"])
        self.assertEqual("FILLED", record["paper_money_result"])
        self.assertEqual(9.99, record["paper_money_fill_price"])

    def test_exact_duplicate_is_idempotent_without_rewriting_artifact(self) -> None:
        first = self.record()
        artifact_before = first.path.read_bytes()

        second = self.record(
            recorded_at=datetime.fromisoformat("2026-07-27T10:06:00-05:00"),
        )

        self.assertFalse(second.created)
        self.assertEqual(first.record, second.record)
        self.assertEqual(artifact_before, second.path.read_bytes())

    def test_concurrent_source_change_fails_closed_for_existing_record(self) -> None:
        self.record()
        with patch(
            "momentum_hunter.shadow_paper_reconciliation._source_matches",
            return_value=False,
        ):
            with self.assertRaisesRegex(Exception, "state changed"):
                self.record()

    def test_conflicting_second_record_is_rejected_and_first_is_preserved(self) -> None:
        first = self.record()
        artifact_before = first.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "different write-once"):
            self.record(reconciliation_notes="A conflicting second observation.")

        self.assertEqual(artifact_before, first.path.read_bytes())

    def test_tampered_existing_record_fails_fingerprint_validation(self) -> None:
        first = self.record()
        payload = json.loads(first.path.read_text(encoding="utf-8"))
        payload["reconciliation"]["paper_money_fill_price"] = 10.25
        first.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "malformed"):
            self.record()

    def test_missing_trade_and_missing_ticket_fail_closed(self) -> None:
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.record(shadow_trade_id="shadow-trade-missing")
        self.assertEqual(before, self.state_path.read_bytes())

        state = self.service.store.load()
        no_ticket = replace(state.trades[0], ticket=None)
        self.state_path.write_text(
            json.dumps(
                shadow_state_to_dict(replace(state, trades=(no_ticket,))),
                indent=2,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "no nontransmitting ticket"):
            self.record()
        self.assertFalse(self.output_dir.exists())

    def test_invalid_result_and_fill_combinations_fail_without_artifact(self) -> None:
        scenarios = (
            ({"paper_money_result": "FILLED", "paper_money_fill_price": None}, "required"),
            (
                {"paper_money_result": "REJECTED", "paper_money_fill_price": 10.0},
                "must be omitted",
            ),
            (
                {"paper_money_result": "MYSTERY", "paper_money_fill_price": None},
                "must be one of",
            ),
            (
                {"paper_money_result": "FILLED", "paper_money_fill_price": float("nan")},
                "required",
            ),
        )
        for overrides, expected in scenarios:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, expected):
                    self.record(**overrides)
                self.assertFalse(self.output_dir.exists())

    def test_reconciliation_timestamp_cannot_precede_frozen_ticket(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            self.record(
                recorded_at=datetime.fromisoformat(
                    "2026-07-27T09:59:59-05:00"
                )
            )
        self.assertFalse(self.output_dir.exists())

    def test_tampered_ticket_binding_and_embedded_reconciliation_fail_closed(self) -> None:
        state = self.service.store.load()
        ticket = state.trades[0].ticket
        assert ticket is not None
        tampered_trade = replace(
            state.trades[0],
            ticket=replace(ticket, trade_plan_id="tp-other"),
        )
        self.state_path.write_text(
            json.dumps(
                shadow_state_to_dict(replace(state, trades=(tampered_trade,))),
                indent=2,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "TradePlan identifier"):
            self.record()

        embedded_trade = replace(
            state.trades[0],
            ticket=replace(ticket, paper_money_result="FILLED"),
        )
        self.state_path.write_text(
            json.dumps(
                shadow_state_to_dict(replace(state, trades=(embedded_trade,))),
                indent=2,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "embedded"):
            self.record()

    def test_output_cannot_be_state_file_or_unbounded_existing_artifact(self) -> None:
        with self.assertRaisesRegex(ValueError, "directory"):
            self.record(output_dir=self.state_path)

        self.output_dir.mkdir()
        target = (
            self.output_dir
            / f"paper-reconciliation-{self.trade.shadow_trade_id}.json"
        )
        target.write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cannot be loaded"):
            self.record()

    def test_cli_records_evidence_and_reports_all_execution_flags_false(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            exit_code = main(
                [
                    "--state-path",
                    str(self.state_path),
                    "--output-dir",
                    str(self.output_dir),
                    "--trade-id",
                    self.trade.shadow_trade_id,
                    "--exact-ticket-entered",
                    "BUY 2 TEST LIMIT 10.00 DAY REGULAR",
                    "--result",
                    "NOT_FILLED",
                    "--notes",
                    "Order was not filled in paperMoney.",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["created"])
        self.assertTrue(payload["sourceStateUnchanged"])
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["brokerRequestPerformed"])
        self.assertFalse(payload["orderActionPerformed"])

    def test_module_declares_no_network_broker_or_order_action_capability(self) -> None:
        source_path = Path(reconciliation_module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(
            {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "momentum_hunter.schwab_client",
            }
            & imports
        )
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(
            {"submit_order", "replace_order", "cancel_order", "send_order"}
            & function_names
        )


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
            "generated_at": "2026-07-27T09:59:00-05:00",
            "source_capture_path": "synthetic/capture.json",
            "source_capture_time": "2026-07-27T09:58:00-05:00",
            "source_provider": "synthetic-test-provider",
            "source_scanner": "Institutional Momentum",
            "market_regime": "risk_on",
        },
        "top_5_for_capital": [row],
        "candidates": [row],
    }


if __name__ == "__main__":
    unittest.main()
