from __future__ import annotations

import ast
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_paper_model_error as model_error_module
from momentum_hunter.shadow_paper_model_error import (
    PaperMoneyModelErrorError,
    _summarize_records,
    build_paper_money_model_error_audit,
    export_paper_money_model_error_audit,
    main,
)
from momentum_hunter.shadow_paper_reconciliation import (
    record_paper_money_reconciliation,
)
from momentum_hunter.shadow_trading import (
    MIN_MEANINGFUL_SAMPLE_SIZE,
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
)


class PaperMoneyModelErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "trade-plan.json"
        self.state_path = self.root / "shadow-state.json"
        self.evidence_dir = self.root / "paper-reconciliations"
        self.output_dir = self.root / "reports"
        self.report_path.write_text(
            json.dumps(_report_payload()),
            encoding="utf-8",
        )
        service = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
        )
        trade = service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="paper-model-error-test",
            decision_at=datetime.fromisoformat(
                "2026-07-27T10:00:00-05:00"
            ),
        )
        service.process_quote(
            _quote(
                "2026-07-27T10:01:00-05:00",
                bid=9.94,
                ask=9.95,
            ),
            received_at=datetime.fromisoformat(
                "2026-07-27T10:01:00-05:00"
            ),
        )
        service.process_quote(
            _quote(
                "2026-07-27T10:30:00-05:00",
                bid=10.55,
                ask=10.56,
                high=10.57,
                low=10.50,
            ),
            received_at=datetime.fromisoformat(
                "2026-07-27T10:30:00-05:00"
            ),
        )
        reconciliation = record_paper_money_reconciliation(
            state_path=self.state_path,
            output_dir=self.evidence_dir,
            shadow_trade_id=trade.shadow_trade_id,
            exact_ticket_entered=(
                "BUY 2 TEST LIMIT 10.00 DAY REGULAR in thinkorswim paperMoney"
            ),
            paper_money_result="FILLED",
            paper_money_fill_price=9.96,
            paper_money_exit_price=10.53,
            paper_money_exit="Target exit entered manually.",
            paper_money_outcome="CLOSED_WIN",
            reconciliation_notes="Synthetic comparison evidence.",
            recorded_at=datetime.fromisoformat(
                "2026-07-27T10:31:00-05:00"
            ),
        )
        self.artifact_path = reconciliation.path
        self.base_record = reconciliation.record
        self.generated_at = datetime.fromisoformat(
            "2026-07-27T11:00:00-05:00"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self):
        return build_paper_money_model_error_audit(
            evidence_dir=self.evidence_dir,
            generated_at=self.generated_at,
        )

    def test_single_valid_record_is_audited_but_metrics_are_withheld(self) -> None:
        before = self.artifact_path.read_bytes()

        payload = self.build()

        self.assertEqual("INSUFFICIENT_SAMPLE", payload["overall_status"])
        self.assertEqual(1, payload["source_record_count"])
        self.assertEqual(
            [self.base_record.fill_model_version],
            payload["fill_model_versions"],
        )
        self.assertFalse(payload["transmitting"])
        self.assertFalse(payload["broker_request_performed"])
        self.assertFalse(payload["order_action_performed"])
        self.assertFalse(payload["strategy_conclusion_authorized"])
        self.assertFalse(payload["trading_authorized"])
        group = payload["fill_model_groups"][0]
        self.assertEqual(1, group["entry_bps"]["observation_count"])
        self.assertFalse(group["entry_bps"]["gate_satisfied"])
        self.assertIsNone(group["entry_bps"]["signed_mean"])
        self.assertEqual(
            "WITHHELD_INSUFFICIENT_SAMPLE",
            group["pnl_per_share"]["status"],
        )
        self.assertEqual(before, self.artifact_path.read_bytes())
        self.assertEqual(
            hashlib.sha256(before).hexdigest(),
            payload["source_manifest"][0]["sha256"],
        )
        projection = payload["records"][0]
        self.assertNotIn("exact_ticket_entered", projection)
        self.assertNotIn("operator_modifications", projection)
        self.assertNotIn("reconciliation_notes", projection)

    def test_no_evidence_is_explicit_and_does_not_create_source_directory(
        self,
    ) -> None:
        missing = self.root / "missing-evidence"

        payload = build_paper_money_model_error_audit(
            evidence_dir=missing,
            generated_at=self.generated_at,
        )

        self.assertEqual("NO_EVIDENCE", payload["overall_status"])
        self.assertEqual(0, payload["source_record_count"])
        self.assertEqual([], payload["fill_model_groups"])
        self.assertFalse(missing.exists())

    def test_threshold_enables_only_descriptive_model_error_metrics(self) -> None:
        records = _synthetic_records(
            self.base_record,
            MIN_MEANINGFUL_SAMPLE_SIZE,
        )

        payload = _summarize_records(
            records,
            generated_at=self.generated_at,
            source_directory=self.evidence_dir,
            source_manifest=[],
            source_manifest_sha256="0" * 64,
            minimum_sample_size=MIN_MEANINGFUL_SAMPLE_SIZE,
        )

        self.assertEqual(
            "DESCRIPTIVE_MODEL_ERROR_READY",
            payload["overall_status"],
        )
        group = payload["fill_model_groups"][0]
        self.assertTrue(group["entry_bps"]["gate_satisfied"])
        self.assertEqual(15.5, group["entry_bps"]["signed_mean"])
        self.assertEqual(15.5, group["entry_bps"]["median"])
        self.assertEqual(
            15.5,
            group["entry_bps"]["mean_absolute_error"],
        )
        self.assertTrue(group["exit_bps"]["gate_satisfied"])
        self.assertEqual(10.0, group["exit_bps"]["signed_mean"])
        self.assertEqual(
            0.01,
            group["pnl_per_share"]["signed_mean"],
        )
        self.assertFalse(payload["strategy_conclusion_authorized"])
        self.assertFalse(payload["trading_authorized"])
        self.assertIn("descriptive model-error metrics only", payload["conclusion"])

    def test_mixed_fill_models_are_never_combined(self) -> None:
        first = _synthetic_records(
            self.base_record,
            15,
            fill_model_version="fill-v1",
        )
        second = _synthetic_records(
            self.base_record,
            15,
            fill_model_version="fill-v2",
            start_index=15,
        )

        payload = _summarize_records(
            [*first, *second],
            generated_at=self.generated_at,
            source_directory=self.evidence_dir,
            source_manifest=[],
            source_manifest_sha256="0" * 64,
            minimum_sample_size=MIN_MEANINGFUL_SAMPLE_SIZE,
        )

        self.assertEqual(
            "MIXED_FILL_MODEL_VERSIONS",
            payload["overall_status"],
        )
        self.assertEqual(["fill-v1", "fill-v2"], payload["fill_model_versions"])
        self.assertEqual(2, len(payload["fill_model_groups"]))
        self.assertTrue(
            all(
                not group["pnl_per_share"]["gate_satisfied"]
                for group in payload["fill_model_groups"]
            )
        )
        self.assertIn("must not be combined", payload["conclusion"])

    def test_duplicate_trade_or_reconciliation_identity_fails_closed(
        self,
    ) -> None:
        duplicate_trade = replace(
            self.base_record,
            reconciliation_id="paper-reconciliation-other",
        )
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "Duplicate Shadow Trade",
        ):
            self._summarize([self.base_record, duplicate_trade])

        duplicate_reconciliation = replace(
            self.base_record,
            shadow_trade_id="shadow-trade-other",
        )
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "Duplicate reconciliation",
        ):
            self._summarize([self.base_record, duplicate_reconciliation])

        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "no frozen fill-model version",
        ):
            self._summarize(
                [replace(self.base_record, fill_model_version="")]
            )

    def test_tampered_or_renamed_artifact_fails_closed(self) -> None:
        original = self.artifact_path.read_bytes()
        payload = json.loads(original.decode("utf-8"))
        payload["reconciliation"]["paper_minus_fake_pnl_per_share"] = 999
        self.artifact_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "Invalid paperMoney reconciliation",
        ):
            self.build()

        self.artifact_path.write_bytes(original)
        renamed = self.artifact_path.with_name(
            "paper-reconciliation-shadow-trade-renamed.json"
        )
        self.artifact_path.replace(renamed)
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "filename does not match",
        ):
            self.build()

    def test_source_change_during_audit_fails_closed(self) -> None:
        original_loader = (
            model_error_module.load_paper_money_reconciliation
        )

        def load_then_change(path: Path):
            record = original_loader(path)
            path.write_bytes(path.read_bytes() + b" ")
            return record

        with patch.object(
            model_error_module,
            "load_paper_money_reconciliation",
            side_effect=load_then_change,
        ):
            with self.assertRaisesRegex(
                PaperMoneyModelErrorError,
                "changed while",
            ):
                self.build()

    def test_export_and_cli_are_derived_nontransmitting_outputs(self) -> None:
        before = self.artifact_path.read_bytes()
        payload = self.build()

        json_path, markdown_path = export_paper_money_model_error_audit(
            payload,
            output_dir=self.output_dir,
        )

        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        written = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual("INSUFFICIENT_SAMPLE", written["overall_status"])
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("read-only, nontransmitting", markdown)
        self.assertIn("Trading authorized: no", markdown)
        self.assertEqual(before, self.artifact_path.read_bytes())

        cli_output = io.StringIO()
        cli_dir = self.root / "cli-reports"
        with patch("sys.stdout", cli_output):
            exit_code = main(
                [
                    "--evidence-dir",
                    str(self.evidence_dir),
                    "--output-dir",
                    str(cli_dir),
                ]
            )
        summary = json.loads(cli_output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual("INSUFFICIENT_SAMPLE", summary["overallStatus"])
        self.assertFalse(summary["transmitting"])
        self.assertFalse(summary["brokerRequestPerformed"])
        self.assertFalse(summary["orderActionPerformed"])
        self.assertEqual(before, self.artifact_path.read_bytes())

    def test_export_refuses_to_write_inside_source_evidence(self) -> None:
        payload = self.build()

        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "cannot be written inside",
        ):
            export_paper_money_model_error_audit(
                payload,
                output_dir=self.evidence_dir / "derived",
            )
        self.assertFalse((self.evidence_dir / "derived").exists())

    def test_canonical_gate_and_aware_clock_cannot_be_weakened(self) -> None:
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "cannot be lower",
        ):
            build_paper_money_model_error_audit(
                evidence_dir=self.evidence_dir,
                generated_at=self.generated_at,
                minimum_sample_size=MIN_MEANINGFUL_SAMPLE_SIZE - 1,
            )
        with self.assertRaisesRegex(
            PaperMoneyModelErrorError,
            "UTC offset",
        ):
            build_paper_money_model_error_audit(
                evidence_dir=self.evidence_dir,
                generated_at=datetime(2026, 7, 27, 11, 0),
            )

    def test_module_has_no_network_broker_or_order_action_capability(self) -> None:
        source_path = Path(model_error_module.__file__)
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

    def _summarize(self, records):
        return _summarize_records(
            records,
            generated_at=self.generated_at,
            source_directory=self.evidence_dir,
            source_manifest=[],
            source_manifest_sha256="0" * 64,
            minimum_sample_size=MIN_MEANINGFUL_SAMPLE_SIZE,
        )


def _synthetic_records(
    base,
    count: int,
    *,
    fill_model_version: str = "fill-v1",
    start_index: int = 0,
):
    start = datetime.fromisoformat("2026-07-27T10:31:00-05:00")
    records = []
    for offset in range(count):
        index = start_index + offset
        records.append(
            replace(
                base,
                reconciliation_id=f"paper-reconciliation-synthetic-{index}",
                request_fingerprint=f"{index:064x}",
                recorded_at=(start + timedelta(minutes=index)).isoformat(),
                shadow_trade_id=f"shadow-trade-synthetic-{index}",
                shadow_order_id=f"shadow-order-synthetic-{index}",
                fill_model_version=fill_model_version,
                fakebroker_exit_price=10.0,
                paper_minus_fake_entry_bps=float(index + 1),
                paper_minus_fake_exit_price=0.01,
                paper_minus_fake_executable_pnl=0.02,
                paper_minus_fake_pnl_per_share=0.01,
            )
        )
    return records


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


def _quote(
    timestamp: str,
    *,
    bid: float,
    ask: float,
    high: float | None = None,
    low: float | None = None,
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
        source="synthetic-paper-model-error",
    )


if __name__ == "__main__":
    unittest.main()
