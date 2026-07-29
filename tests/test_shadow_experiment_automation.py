from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_experiment_automation as automation_module
from momentum_hunter.shadow_experiment_automation import (
    SHADOW_EXPERIMENT_AUTOMATION_MODE,
    ShadowExperimentAutomationError,
    automate_shadow_experiment_evidence,
    load_shadow_experiment_automation_receipt,
)
from momentum_hunter.shadow_trading import (
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
)
from momentum_hunter.workstation_shadow import (
    ShadowWorkspacePaths,
    ShadowWorkspaceService,
)
from tests.test_shadow_experiment_pipeline import (
    _at,
    _report_payload,
)


class ShadowExperimentAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "shadow-state.json"
        self.report_path = self.root / "trade-plan.json"
        self.experiments_dir = self.root / "reports" / "experiments"
        self.studies_dir = self.root / "reports" / "studies"
        self.receipts_dir = self.root / "reports" / "receipts"
        self.report_path.write_text(
            json.dumps(_two_candidate_report()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def automate(self):
        return automate_shadow_experiment_evidence(
            state_path=self.state_path,
            decision_cycles_path=(
                self.service.decision_cycle_store.path
            ),
            experiments_dir=self.experiments_dir,
            studies_dir=self.studies_dir,
            receipts_dir=self.receipts_dir,
        )

    def start_trade(
        self,
        *,
        symbol: str = "TEST",
        command_id: str = "automation-command-1",
    ):
        return self.service.start_trade(
            self.report_path,
            symbol=symbol,
            simulation_command_id=command_id,
            decision_at=_at("2026-07-29T09:00:00-05:00"),
        )

    def complete_trade(self):
        trade = self.start_trade()
        self.service.process_quote(
            _quote(
                "TEST",
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
                "TEST",
                "2026-07-29T09:30:00-05:00",
                bid=10.55,
                ask=10.56,
                high=10.57,
                low=9.90,
            ),
            received_at=_at("2026-07-29T09:30:00-05:00"),
        )
        return self.service.store.load().trades[0]

    def test_absent_and_pending_state_do_not_create_evidence(self) -> None:
        absent = self.automate()

        self.assertEqual("NO_TERMINAL_TRADES", absent.status)
        self.assertEqual(0, absent.terminal_trade_count)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.receipts_dir.exists())
        self.assertFalse(self.experiments_dir.exists())
        self.start_trade()
        state_before = self.state_path.read_bytes()

        pending = self.automate()

        self.assertEqual("NO_TERMINAL_TRADES", pending.status)
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertFalse(self.receipts_dir.exists())
        self.assertFalse(self.experiments_dir.exists())

    def test_terminal_trade_generates_once_then_is_up_to_date(self) -> None:
        trade = self.complete_trade()
        state_before = self.state_path.read_bytes()

        first = self.automate()
        repeated = self.automate()

        self.assertEqual("EVIDENCE_GENERATED", first.status)
        self.assertEqual("UP_TO_DATE", repeated.status)
        self.assertEqual((trade.shadow_trade_id,), first.terminal_trade_ids)
        self.assertTrue(first.receipt_created)
        self.assertFalse(repeated.receipt_created)
        self.assertEqual(first.receipt_id, repeated.receipt_id)
        self.assertEqual(first.experiment_ids, repeated.experiment_ids)
        self.assertEqual(first.study_id, repeated.study_id)
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertFalse(first.transmitting)
        self.assertFalse(first.broker_request_performed)
        self.assertFalse(first.order_action_performed)
        receipt = load_shadow_experiment_automation_receipt(
            first.receipt_path
        )
        self.assertEqual(
            SHADOW_EXPERIMENT_AUTOMATION_MODE,
            receipt["mode"],
        )

    def test_active_trade_changes_do_not_repeat_terminal_pipeline(self) -> None:
        self.complete_trade()
        first = self.automate()
        self.start_trade(
            symbol="NEXT",
            command_id="automation-command-2",
        )
        self.service.process_quote(
            _quote(
                "NEXT",
                "2026-07-29T09:31:00-05:00",
                bid=19.94,
                ask=19.95,
                high=19.96,
                low=19.93,
            ),
            received_at=_at("2026-07-29T09:31:00-05:00"),
        )

        with patch.object(
            automation_module,
            "run_shadow_experiment_pipeline",
            side_effect=AssertionError(
                "Unchanged terminal evidence must not rerun the pipeline."
            ),
        ):
            repeated = self.automate()

        self.assertEqual("UP_TO_DATE", repeated.status)
        self.assertEqual(first.receipt_id, repeated.receipt_id)
        self.assertEqual(
            1,
            len(tuple(self.receipts_dir.glob("*.json"))),
        )

    def test_pipeline_failure_leaves_no_receipt_and_next_run_recovers(
        self,
    ) -> None:
        self.complete_trade()
        with patch.object(
            automation_module,
            "run_shadow_experiment_pipeline",
            side_effect=RuntimeError("synthetic write failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic write failure",
            ):
                self.automate()

        self.assertFalse(self.receipts_dir.exists())

        recovered = self.automate()

        self.assertEqual("EVIDENCE_GENERATED", recovered.status)
        self.assertTrue(recovered.receipt_path.exists())

    def test_source_change_during_pipeline_writes_no_receipt(self) -> None:
        self.complete_trade()
        original = automation_module.run_shadow_experiment_pipeline

        def mutate_after_pipeline(**kwargs):
            result = original(**kwargs)
            payload = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
            payload["updated_at"] = "2026-07-29T10:00:00-05:00"
            self.state_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            return result

        with patch.object(
            automation_module,
            "run_shadow_experiment_pipeline",
            side_effect=mutate_after_pipeline,
        ):
            with self.assertRaisesRegex(
                ShadowExperimentAutomationError,
                "changed during automation",
            ):
                self.automate()

        self.assertFalse(self.receipts_dir.exists())

    def test_tampered_receipt_fails_closed(self) -> None:
        self.complete_trade()
        first = self.automate()
        envelope = json.loads(
            first.receipt_path.read_text(encoding="utf-8")
        )
        envelope["receipt"]["pipeline_status"] = "TAMPERED"
        first.receipt_path.write_text(
            json.dumps(envelope),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ShadowExperimentAutomationError,
            "hash is invalid",
        ):
            self.automate()

    def test_missing_referenced_artifact_is_not_reported_up_to_date(
        self,
    ) -> None:
        self.complete_trade()
        first = self.automate()
        receipt = load_shadow_experiment_automation_receipt(
            first.receipt_path
        )
        markdown_path = Path(
            receipt["study_artifact"]["markdown_path"]
        )
        markdown_path.unlink()

        with self.assertRaisesRegex(
            ShadowExperimentAutomationError,
            "missing or invalid",
        ):
            self.automate()

    def test_receipt_cannot_redirect_artifact_reads(self) -> None:
        self.complete_trade()
        first = self.automate()
        envelope = json.loads(
            first.receipt_path.read_text(encoding="utf-8")
        )
        envelope["receipt"]["experiment_artifacts"][0][
            "json_path"
        ] = str(self.report_path)
        envelope["receipt"]["experiment_artifacts"][0][
            "json_sha256"
        ] = hashlib.sha256(self.report_path.read_bytes()).hexdigest()
        envelope["receipt_sha256"] = hashlib.sha256(
            automation_module.canonical_json(
                envelope["receipt"]
            ).encode("utf-8")
        ).hexdigest()
        first.receipt_path.write_text(
            json.dumps(envelope),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ShadowExperimentAutomationError,
            "outside its configured directory",
        ):
            self.automate()

    def test_workspace_runs_automation_after_observation_finalization(
        self,
    ) -> None:
        self.complete_trade()
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                reports_dir=self.root / "reports",
                observations_path=self.root / "observations.json",
                state_path=self.state_path,
            ),
            service=self.service,
            evidence_checkpoint_generator=lambda _: {
                "status": "NO_CHECKPOINT_DUE"
            },
        )

        first = workspace.advance_observations(
            received_at=_at("2026-07-29T09:31:00-05:00")
        )
        repeated = workspace.advance_observations(
            received_at=_at("2026-07-29T09:32:00-05:00")
        )

        self.assertEqual(
            "EVIDENCE_GENERATED",
            first["experimentEvidence"]["status"],
        )
        self.assertEqual(
            "UP_TO_DATE",
            repeated["experimentEvidence"]["status"],
        )
        self.assertEqual(
            0,
            first["activeTradeCount"],
        )

    def test_runtime_module_has_no_provider_broker_or_order_capability(
        self,
    ) -> None:
        source_path = (
            Path(automation_module.__file__).resolve()
        )
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            str(node.module or "")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        self.assertFalse(
            any(
                token in name.casefold()
                for name in imports
                for token in (
                    "schwab",
                    "requests",
                    "broker",
                    "execution.adapter",
                )
            )
        )
        self.assertNotIn("submit_order", source)
        self.assertNotIn("place_order", source)
        self.assertNotIn("cancel_order", source)


def _two_candidate_report() -> dict:
    payload = _report_payload()
    first = payload["candidates"][0]
    second = json.loads(json.dumps(first))
    second["rank"] = 2
    second["symbol"] = "NEXT"
    second["company"] = "Synthetic Next Corporation"
    second["market_data"]["last_price"] = 19.9
    second["market_data"]["current_bid"] = 19.89
    second["market_data"]["current_ask"] = 19.91
    second["trade_plan"]["bullish_entry"] = 20.0
    second["trade_plan"]["bullish_stop"] = 19.5
    second["trade_plan"]["bullish_target_1"] = 20.5
    second["trade_plan"]["bullish_target_2"] = 21.0
    payload["candidates"] = [first, second]
    payload["top_5_for_capital"] = [first, second]
    return payload


def _quote(
    symbol: str,
    timestamp: str,
    *,
    bid: float,
    ask: float,
    high: float,
    low: float,
) -> ShadowQuote:
    return ShadowQuote(
        symbol=symbol,
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


if __name__ == "__main__":
    unittest.main()
