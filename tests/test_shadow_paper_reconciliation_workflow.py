from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_paper_reconciliation_workflow as workflow_module
from momentum_hunter.shadow_experiment_automation import (
    automate_shadow_experiment_evidence,
)
from momentum_hunter.shadow_paper_reconciliation import main
from momentum_hunter.shadow_paper_reconciliation_workflow import (
    PAPER_RECONCILIATION_WORKFLOW_MODE,
    record_and_refresh_paper_money_evidence,
)
from momentum_hunter.shadow_trade_experiments import (
    load_shadow_trade_experiment,
)
from momentum_hunter.shadow_trading import (
    ShadowStateStore,
    ShadowTradingService,
)
from tests.test_shadow_experiment_automation import (
    _at,
    _quote,
    _two_candidate_report,
)


class PaperMoneyReconciliationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "shadow-state.json"
        self.report_path = self.root / "trade-plan.json"
        self.reconciliations_dir = (
            self.root / "evidence" / "paper-reconciliations"
        )
        self.experiments_dir = (
            self.root / "evidence" / "experiments"
        )
        self.studies_dir = self.root / "evidence" / "studies"
        self.receipts_dir = self.root / "evidence" / "receipts"
        self.report_path.write_text(
            json.dumps(_two_candidate_report()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path)
        )
        self.trade = self.service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="paper-workflow-command",
            decision_at=_at("2026-07-29T09:00:00-05:00"),
        )
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
        self.trade = self.service.store.load().trades[0]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_workflow(self):
        return record_and_refresh_paper_money_evidence(
            state_path=self.state_path,
            output_dir=self.reconciliations_dir,
            decision_cycles_path=(
                self.service.decision_cycle_store.path
            ),
            experiments_dir=self.experiments_dir,
            studies_dir=self.studies_dir,
            automation_receipts_dir=self.receipts_dir,
            shadow_trade_id=self.trade.shadow_trade_id,
            exact_ticket_entered=(
                "BUY 2 TEST LIMIT 10.00 DAY REGULAR "
                "in thinkorswim paperMoney"
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

    def test_workflow_immediately_refreshes_terminal_experiment(
        self,
    ) -> None:
        state_before = self.state_path.read_bytes()

        result = self.run_workflow()

        self.assertEqual(
            PAPER_RECONCILIATION_WORKFLOW_MODE,
            result.mode,
        )
        self.assertTrue(result.reconciliation.created)
        self.assertEqual(
            "EVIDENCE_GENERATED",
            result.experiment_evidence.status,
        )
        self.assertEqual(state_before, self.state_path.read_bytes())
        experiment_paths = tuple(self.experiments_dir.glob("*.json"))
        self.assertEqual(1, len(experiment_paths))
        experiment = load_shadow_trade_experiment(
            experiment_paths[0]
        )
        self.assertEqual(
            "PASS",
            experiment["paper_money_reconciliation"][
                "evidence_status"
            ],
        )
        self.assertFalse(result.transmitting)
        self.assertFalse(result.broker_request_performed)
        self.assertFalse(result.order_action_performed)

    def test_identical_retry_does_not_rewrite_evidence(self) -> None:
        first = self.run_workflow()
        reconciliation_before = (
            first.reconciliation.path.read_bytes()
        )

        repeated = self.run_workflow()

        self.assertFalse(repeated.reconciliation.created)
        self.assertEqual(
            "UP_TO_DATE",
            repeated.experiment_evidence.status,
        )
        self.assertEqual(
            first.experiment_evidence.receipt_id,
            repeated.experiment_evidence.receipt_id,
        )
        self.assertEqual(
            reconciliation_before,
            repeated.reconciliation.path.read_bytes(),
        )

    def test_reconciliation_supersedes_prior_terminal_receipt(
        self,
    ) -> None:
        prior = automate_shadow_experiment_evidence(
            state_path=self.state_path,
            decision_cycles_path=(
                self.service.decision_cycle_store.path
            ),
            paper_reconciliations_dir=self.reconciliations_dir,
            experiments_dir=self.experiments_dir,
            studies_dir=self.studies_dir,
            receipts_dir=self.receipts_dir,
        )

        refreshed = self.run_workflow()

        self.assertEqual("EVIDENCE_GENERATED", prior.status)
        self.assertEqual(
            "EVIDENCE_GENERATED",
            refreshed.experiment_evidence.status,
        )
        self.assertNotEqual(
            prior.receipt_id,
            refreshed.experiment_evidence.receipt_id,
        )
        self.assertEqual(
            2,
            len(tuple(self.receipts_dir.glob("*.json"))),
        )
        experiments = [
            load_shadow_trade_experiment(path)
            for path in self.experiments_dir.glob("*.json")
        ]
        self.assertEqual(2, len(experiments))
        self.assertEqual(
            {"NOT_RECORDED", "PASS"},
            {
                item["paper_money_reconciliation"][
                    "evidence_status"
                ]
                for item in experiments
            },
        )

    def test_refresh_failure_preserves_record_and_retry_recovers(
        self,
    ) -> None:
        with patch.object(
            workflow_module,
            "automate_shadow_experiment_evidence",
            side_effect=RuntimeError("synthetic refresh failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic refresh failure",
            ):
                self.run_workflow()

        reconciliation_paths = tuple(
            self.reconciliations_dir.glob("*.json")
        )
        self.assertEqual(1, len(reconciliation_paths))
        self.assertFalse(self.receipts_dir.exists())

        recovered = self.run_workflow()

        self.assertFalse(recovered.reconciliation.created)
        self.assertEqual(
            "EVIDENCE_GENERATED",
            recovered.experiment_evidence.status,
        )
        self.assertTrue(
            recovered.experiment_evidence.receipt_path.exists()
        )

    def test_cli_returns_reconciliation_and_refresh_evidence(self) -> None:
        output = io.StringIO()
        with (
            patch(
                "momentum_hunter.shadow_paper_reconciliation.now_central",
                return_value=_at("2026-07-29T09:31:00-05:00"),
            ),
            redirect_stdout(output),
        ):
            exit_code = main(
                [
                    "--state-path",
                    str(self.state_path),
                    "--output-dir",
                    str(self.reconciliations_dir),
                    "--decision-cycles-path",
                    str(self.service.decision_cycle_store.path),
                    "--experiments-dir",
                    str(self.experiments_dir),
                    "--studies-dir",
                    str(self.studies_dir),
                    "--automation-receipts-dir",
                    str(self.receipts_dir),
                    "--trade-id",
                    self.trade.shadow_trade_id,
                    "--exact-ticket-entered",
                    (
                        "BUY 2 TEST LIMIT 10.00 DAY REGULAR "
                        "in thinkorswim paperMoney"
                    ),
                    "--result",
                    "FILLED",
                    "--fill-price",
                    "9.96",
                    "--exit-price",
                    "10.53",
                    "--operator-modifications",
                    "None",
                    "--exit",
                    "Manual target exit.",
                    "--outcome",
                    "CLOSED_WIN",
                    "--notes",
                    "Synthetic model comparison.",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["created"])
        self.assertEqual(
            "EVIDENCE_GENERATED",
            payload["experimentEvidence"]["status"],
        )
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["brokerRequestPerformed"])
        self.assertFalse(payload["orderActionPerformed"])

    def test_workflow_has_no_provider_broker_or_order_imports(self) -> None:
        source = Path(workflow_module.__file__).read_text(
            encoding="utf-8"
        )
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


if __name__ == "__main__":
    unittest.main()
