from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import momentum_hunter.shadow_experiment_pipeline as pipeline_module
from momentum_hunter.shadow_experiment_pipeline import (
    SHADOW_EXPERIMENT_PIPELINE_MODE,
    ShadowExperimentPipelineError,
    main,
    run_shadow_experiment_pipeline,
)
from momentum_hunter.shadow_paper_reconciliation import (
    record_paper_money_reconciliation,
)
from momentum_hunter.shadow_trading import (
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
)


class ShadowExperimentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "shadow-state.json"
        self.report_path = self.root / "trade-plan.json"
        self.experiments_dir = self.root / "experiments"
        self.studies_dir = self.root / "studies"
        self.report_path.write_text(
            json.dumps(_report_payload()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_pipeline(self):
        return run_shadow_experiment_pipeline(
            state_path=self.state_path,
            experiments_dir=self.experiments_dir,
            studies_dir=self.studies_dir,
        )

    def start_trade(self, *, command_id: str = "pipeline-command-1"):
        return self.service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id=command_id,
            decision_at=_at("2026-07-29T09:00:00-05:00"),
        )

    def complete_trade(self):
        trade = self.start_trade()
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
        return self.service.store.load().trades[0]

    def test_absent_state_produces_truthful_withheld_study_without_state(
        self,
    ) -> None:
        self.assertFalse(self.state_path.exists())

        first = self.run_pipeline()
        repeated = self.run_pipeline()

        self.assertEqual("NO_TRADES_STUDY_WITHHELD", first.status)
        self.assertEqual(0, first.trade_count)
        self.assertIsNone(first.source_state_sha256)
        self.assertIsNone(first.active_sample_version)
        self.assertEqual((), first.experiment_writes)
        self.assertTrue(first.study_write.created)
        self.assertFalse(repeated.study_write.created)
        self.assertFalse(self.state_path.exists())
        self.assertTrue(first.source_artifacts_unchanged)
        self.assertFalse(first.transmitting)
        self.assertFalse(first.broker_request_performed)
        self.assertFalse(first.order_action_performed)
        study = _study(first.study_write.json_path)
        self.assertEqual(0, study["sample_gate"]["eligible_completed"])
        self.assertEqual(
            "WITHHELD_BELOW_30",
            study["sample_gate"]["metrics_status"],
        )

    def test_activation_selects_official_sample_without_creating_state(
        self,
    ) -> None:
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=_at("2026-07-29T08:00:00-05:00"),
        ):
            activation = self.service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
            )
        activation_path = self.service.activation_store.path
        activation_before = activation_path.read_bytes()
        self.assertFalse(self.state_path.exists())

        result = self.run_pipeline()

        self.assertEqual(
            activation.sample_metadata.sample_version,
            result.active_sample_version,
        )
        self.assertEqual(
            activation_before,
            activation_path.read_bytes(),
        )
        self.assertFalse(self.state_path.exists())
        study = _study(result.study_write.json_path)
        self.assertEqual(
            activation.sample_metadata.sample_version,
            study["sample_version"],
        )

    def test_pending_trade_generates_idempotent_report_and_study(
        self,
    ) -> None:
        trade = self.start_trade()
        state_before = self.state_path.read_bytes()
        report_before = self.report_path.read_bytes()

        first = self.run_pipeline()
        repeated = self.run_pipeline()

        self.assertEqual(
            "REPORTS_AND_STUDY_AVAILABLE",
            first.status,
        )
        self.assertEqual(1, first.trade_count)
        self.assertEqual(1, len(first.experiment_writes))
        self.assertTrue(first.experiment_writes[0].created)
        self.assertFalse(repeated.experiment_writes[0].created)
        self.assertTrue(first.study_write.created)
        self.assertFalse(repeated.study_write.created)
        self.assertEqual(
            trade.shadow_trade_id,
            first.experiment_writes[0].shadow_trade_id,
        )
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(report_before, self.report_path.read_bytes())
        experiment = _experiment(first.experiment_writes[0].json_path)
        self.assertEqual(
            "PENDING_OR_UNFILLED",
            experiment["artifact_status"],
        )
        study = _study(first.study_write.json_path)
        self.assertEqual(1, study["collection"]["artifact_count"])
        self.assertEqual(0, study["sample_gate"]["eligible_completed"])

    def test_completed_trade_and_paper_delta_flow_into_batch_outputs(
        self,
    ) -> None:
        trade = self.complete_trade()
        reconciliation = record_paper_money_reconciliation(
            state_path=self.state_path,
            output_dir=self.root / "paper-reconciliations",
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
            reconciliation_notes="Synthetic pipeline comparison.",
            recorded_at=_at("2026-07-29T09:31:00-05:00"),
        )
        state_before = self.state_path.read_bytes()
        reconciliation_before = reconciliation.path.read_bytes()

        result = self.run_pipeline()

        experiment = _experiment(
            result.experiment_writes[0].json_path
        )
        self.assertEqual("COMPLETE", experiment["artifact_status"])
        self.assertEqual(
            "PASS",
            experiment["paper_money_reconciliation"][
                "evidence_status"
            ],
        )
        self.assertEqual(
            "FULL_LIFECYCLE_COMPARISON",
            experiment["paper_money_reconciliation"][
                "comparison_status"
            ],
        )
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(
            reconciliation_before,
            reconciliation.path.read_bytes(),
        )

    def test_later_state_hash_supersedes_equivalent_final_snapshot(
        self,
    ) -> None:
        self.complete_trade()
        first = self.run_pipeline()
        first_study = _study(first.study_write.json_path)
        self.assertEqual(1, first_study["collection"]["artifact_count"])

        state = self.service.store.load()
        self.service.store.save(state)
        second = self.run_pipeline()
        second_study = _study(second.study_write.json_path)

        self.assertEqual(2, second_study["collection"]["artifact_count"])
        self.assertEqual(
            1,
            second_study["collection"]["unique_trade_count"],
        )
        self.assertEqual(
            1,
            second_study["collection"]["superseded_snapshot_count"],
        )
        self.assertTrue(second.study_write.created)

    def test_state_change_during_batch_is_detected_after_study(self) -> None:
        self.start_trade()
        original_study = (
            pipeline_module.generate_shadow_experiment_study
        )

        def mutate_after_study(**kwargs):
            result = original_study(**kwargs)
            payload = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
            payload["updated_at"] = "2026-07-29T09:01:00-05:00"
            self.state_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            return result

        with patch.object(
            pipeline_module,
            "generate_shadow_experiment_study",
            side_effect=mutate_after_study,
        ), self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "changed during the batch",
        ):
            self.run_pipeline()

    def test_missing_state_created_during_batch_is_detected(self) -> None:
        original_study = (
            pipeline_module.generate_shadow_experiment_study
        )

        def create_state_after_study(**kwargs):
            result = original_study(**kwargs)
            self.state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "engine_version": "shadow_trading_v1",
                        "updated_at": "",
                        "trades": [],
                        "command_receipts": [],
                    }
                ),
                encoding="utf-8",
            )
            return result

        with patch.object(
            pipeline_module,
            "generate_shadow_experiment_study",
            side_effect=create_state_after_study,
        ), self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "changed during the batch",
        ):
            self.run_pipeline()

    def test_output_path_file_fails_before_source_mutation(self) -> None:
        self.start_trade()
        state_before = self.state_path.read_bytes()
        self.experiments_dir.write_text("not a directory", encoding="utf-8")

        with self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "must identify a directory",
        ):
            self.run_pipeline()

        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertFalse(self.studies_dir.exists())

    def test_invalid_study_path_fails_before_experiment_write(self) -> None:
        self.start_trade()
        state_before = self.state_path.read_bytes()
        self.studies_dir.write_text("not a directory", encoding="utf-8")

        with self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "study output path",
        ):
            self.run_pipeline()

        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertFalse(self.experiments_dir.exists())

    def test_activation_and_official_trade_version_conflict_fails(
        self,
    ) -> None:
        trades = (
            SimpleNamespace(
                sample_metadata=SimpleNamespace(
                    sample_version="official-shadow-v2",
                    official_sample_authorized=True,
                )
            ),
        )

        with self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "activation conflicts",
        ):
            pipeline_module._active_sample_version(
                trades,
                "official-shadow-v1",
            )

    def test_source_paths_must_be_distinct(self) -> None:
        with self.assertRaisesRegex(
            ShadowExperimentPipelineError,
            "source paths must be distinct",
        ):
            run_shadow_experiment_pipeline(
                state_path=self.state_path,
                decision_cycles_path=self.state_path,
                experiments_dir=self.experiments_dir,
                studies_dir=self.studies_dir,
            )

    def test_cli_reports_nontransmitting_result(self) -> None:
        output = io.StringIO()

        with patch("sys.stdout", output):
            result = main(
                [
                    "--state-path",
                    str(self.state_path),
                    "--experiments-dir",
                    str(self.experiments_dir),
                    "--studies-dir",
                    str(self.studies_dir),
                ]
            )

        self.assertEqual(0, result)
        payload = json.loads(output.getvalue())
        self.assertEqual(SHADOW_EXPERIMENT_PIPELINE_MODE, payload["mode"])
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["brokerRequestPerformed"])
        self.assertFalse(payload["orderActionPerformed"])
        self.assertTrue(payload["sourceArtifactsUnchanged"])

    def test_module_has_no_provider_broker_or_runtime_mutation_surface(
        self,
    ) -> None:
        source = Path(pipeline_module.__file__).read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
        forbidden = {
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
                if any(fragment in name for fragment in forbidden)
            }
        )
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("evaluate_trade_plan", source)
        self.assertNotIn("process_quote", source)
        self.assertIn(SHADOW_EXPERIMENT_PIPELINE_MODE, source)


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


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _experiment(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["experiment"]


def _study(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["study"]


if __name__ == "__main__":
    unittest.main()
