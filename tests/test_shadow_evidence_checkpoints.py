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

import momentum_hunter.shadow_evidence_checkpoints as checkpoint_module
from momentum_hunter.shadow_evidence_checkpoints import (
    SHADOW_CHECKPOINT_THRESHOLDS,
    ShadowEvidenceCheckpointError,
    build_shadow_evidence_checkpoint_payloads,
    generate_shadow_evidence_checkpoints,
    main,
    write_shadow_evidence_checkpoints,
)
from momentum_hunter.shadow_trading import (
    MIN_MEANINGFUL_SAMPLE_SIZE,
    OFFICIAL_SHADOW_SAMPLE_VERSION,
    SHADOW_MODE,
    ShadowExecutionPolicy,
    ShadowSampleActivation,
    ShadowSampleActivationStore,
    ShadowStateStore,
    ShadowTradingService,
    build_shadow_sample_metadata,
    canonical_json,
    shadow_sample_metadata_to_dict,
)


class ShadowEvidenceCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_dir = self.root / "shadow-state"
        self.state_path = self.source_dir / "shadow-state.json"
        self.activation_path = (
            self.source_dir / "shadow-state-sample-activation.json"
        )
        self.output_dir = self.root / "reports"
        self.generated_at = datetime.fromisoformat(
            "2026-08-14T11:00:00-05:00"
        )
        self.policy = ShadowExecutionPolicy()
        self.metadata = build_shadow_sample_metadata(
            self.policy,
            sample_version=OFFICIAL_SHADOW_SAMPLE_VERSION,
            official_sample_authorized=True,
        )
        self.activation = ShadowSampleActivation(
            schema_version=1,
            activated_at="2026-07-25T18:18:58-05:00",
            sample_metadata=self.metadata,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, count: int, *, generated_at: datetime | None = None):
        return build_shadow_evidence_checkpoint_payloads(
            _snapshot(count, self.metadata),
            activation=self.activation,
            generated_at=generated_at or self.generated_at,
            source_state_path=self.state_path,
            source_state_sha256="a" * 64 if count else None,
            activation_path=self.activation_path,
            activation_sha256="b" * 64,
        )

    def test_exact_five_checkpoint_is_deterministic_and_withheld(self) -> None:
        payloads = self.build(5)

        self.assertEqual(1, len(payloads))
        checkpoint = payloads[0]
        self.assertEqual(5, checkpoint["threshold"])
        self.assertEqual(5, checkpoint["selected_trade_count"])
        self.assertFalse(checkpoint["late_reconstruction"])
        self.assertEqual(
            "CANONICAL_EXACT_COUNT_SNAPSHOT",
            checkpoint["metrics_status"],
        )
        self.assertTrue(
            all(
                checkpoint["metrics"][field] is None
                for field in checkpoint_module.GATED_METRIC_FIELDS
            )
        )
        self.assertFalse(checkpoint["strategy_conclusion_authorized"])
        self.assertFalse(checkpoint["trading_authorized"])
        self.assertFalse(checkpoint["transmitting"])
        self.assertEqual(
            sorted(
                checkpoint["selected_trades"],
                key=lambda row: (
                    row["decisionTimestamp"],
                    row["shadowTradeId"],
                ),
            ),
            checkpoint["selected_trades"],
        )

    def test_checkpoint_orders_by_instant_across_utc_offsets(self) -> None:
        snapshot = _snapshot(5, self.metadata)
        snapshot["reviewTrades"][0]["decisionTimestamp"] = (
            "2026-11-01T01:15:00-06:00"
        )
        snapshot["reviewTrades"][1]["decisionTimestamp"] = (
            "2026-11-01T01:45:00-05:00"
        )
        for index in range(2, 5):
            snapshot["reviewTrades"][index]["decisionTimestamp"] = (
                f"2026-11-01T0{index}:00:00-06:00"
            )

        payloads = build_shadow_evidence_checkpoint_payloads(
            snapshot,
            activation=self.activation,
            generated_at=self.generated_at,
            source_state_path=self.state_path,
            source_state_sha256="a" * 64,
            activation_path=self.activation_path,
            activation_sha256="b" * 64,
        )

        ordered = payloads[0]["selected_trades"]
        self.assertEqual(
            "2026-11-01T01:45:00-05:00",
            ordered[0]["decisionTimestamp"],
        )
        self.assertEqual(
            "2026-11-01T01:15:00-06:00",
            ordered[1]["decisionTimestamp"],
        )

    def test_ten_records_create_late_five_and_exact_ten(self) -> None:
        payloads = self.build(10)

        self.assertEqual([5, 10], [item["threshold"] for item in payloads])
        five, ten = payloads
        self.assertTrue(five["late_reconstruction"])
        self.assertEqual(
            "LATE_RECONSTRUCTION_METRICS_WITHHELD",
            five["metrics_status"],
        )
        self.assertIsNone(five["metrics"])
        self.assertFalse(ten["late_reconstruction"])
        self.assertIsNotNone(ten["metrics"])
        self.assertIn("mechanics and evidence quality", ten["conclusion"])

    def test_exact_thirty_releases_descriptive_metrics_without_authority(
        self,
    ) -> None:
        payloads = self.build(MIN_MEANINGFUL_SAMPLE_SIZE)

        self.assertEqual(
            list(SHADOW_CHECKPOINT_THRESHOLDS),
            [item["threshold"] for item in payloads],
        )
        thirty = payloads[-1]
        self.assertFalse(thirty["late_reconstruction"])
        self.assertEqual(
            "CANONICAL_EXACT_COUNT_SNAPSHOT",
            thirty["metrics_status"],
        )
        self.assertEqual(
            "MEANINGFUL",
            thirty["metrics"]["sampleStatus"],
        )
        self.assertEqual(
            MIN_MEANINGFUL_SAMPLE_SIZE,
            thirty["metrics"]["completedTradeCount"],
        )
        self.assertIsNotNone(thirty["metrics"]["executablePnl"])
        self.assertFalse(thirty["strategy_conclusion_authorized"])
        self.assertFalse(thirty["trading_authorized"])
        self.assertIn("does not prove durable edge", thirty["conclusion"])

    def test_late_thirty_reconstruction_withholds_current_metrics(self) -> None:
        payloads = self.build(31)

        self.assertEqual(4, len(payloads))
        thirty = payloads[-1]
        self.assertTrue(thirty["late_reconstruction"])
        self.assertIsNone(thirty["metrics"])
        self.assertEqual(
            "LATE_RECONSTRUCTION_METRICS_WITHHELD",
            thirty["metrics_status"],
        )

    def test_snapshot_identity_count_and_gate_mismatches_fail_closed(
        self,
    ) -> None:
        scenarios = []
        transmitting = _snapshot(5, self.metadata)
        transmitting["transmitting"] = True
        scenarios.append((transmitting, "nontransmitting"))

        bad_count = _snapshot(5, self.metadata)
        bad_count["sample"]["eligibleCompleted"] = 4
        scenarios.append((bad_count, "eligible count"))

        duplicate = _snapshot(5, self.metadata)
        duplicate["reviewTrades"][1]["shadowTradeId"] = (
            duplicate["reviewTrades"][0]["shadowTradeId"]
        )
        scenarios.append((duplicate, "duplicate trade"))

        exposed = _snapshot(5, self.metadata)
        exposed["reviewMetrics"]["executablePnl"] = 12.34
        scenarios.append((exposed, "exposes gated metrics"))

        wrong_sample = _snapshot(5, self.metadata)
        wrong_sample["reviewTrades"][0]["sampleMetadata"]["sampleVersion"] = (
            "other-sample"
        )
        scenarios.append((wrong_sample, "different sample"))

        for snapshot, expected in scenarios:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(
                    ShadowEvidenceCheckpointError,
                    expected,
                ):
                    build_shadow_evidence_checkpoint_payloads(
                        snapshot,
                        activation=self.activation,
                        generated_at=self.generated_at,
                        source_state_path=self.state_path,
                        source_state_sha256="a" * 64,
                        activation_path=self.activation_path,
                        activation_sha256="b" * 64,
                    )

    def test_write_once_checkpoint_is_idempotent_and_recovers_markdown(
        self,
    ) -> None:
        first_payloads = self.build(5)
        first = write_shadow_evidence_checkpoints(
            first_payloads,
            output_dir=self.output_dir,
        )
        json_before = first[0].json_path.read_bytes()
        markdown_before = first[0].markdown_path.read_bytes()

        later_payloads = self.build(
            5,
            generated_at=self.generated_at + timedelta(hours=1),
        )
        second = write_shadow_evidence_checkpoints(
            later_payloads,
            output_dir=self.output_dir,
        )

        self.assertFalse(second[0].created)
        self.assertEqual(json_before, second[0].json_path.read_bytes())
        self.assertEqual(markdown_before, second[0].markdown_path.read_bytes())

        second[0].markdown_path.unlink()
        recovered = write_shadow_evidence_checkpoints(
            later_payloads,
            output_dir=self.output_dir,
        )
        self.assertFalse(recovered[0].created)
        self.assertEqual(
            markdown_before,
            recovered[0].markdown_path.read_bytes(),
        )

    def test_tampered_json_or_markdown_fails_closed(self) -> None:
        writes = write_shadow_evidence_checkpoints(
            self.build(5),
            output_dir=self.output_dir,
        )
        json_path = writes[0].json_path
        original_json = json_path.read_bytes()
        envelope = json.loads(original_json.decode("utf-8"))
        envelope["checkpoint"]["selected_trades"][0]["symbol"] = "TAMPER"
        json_path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(
            ShadowEvidenceCheckpointError,
            "hash does not match",
        ):
            write_shadow_evidence_checkpoints(
                self.build(5),
                output_dir=self.output_dir,
            )

        json_path.write_bytes(original_json)
        writes[0].markdown_path.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(
            ShadowEvidenceCheckpointError,
            "Markdown is inconsistent",
        ):
            write_shadow_evidence_checkpoints(
                self.build(5),
                output_dir=self.output_dir,
            )

    def test_output_cannot_be_inside_source_state_storage(self) -> None:
        with self.assertRaisesRegex(
            ShadowEvidenceCheckpointError,
            "inside source state",
        ):
            write_shadow_evidence_checkpoints(
                self.build(5),
                output_dir=self.source_dir / "derived",
            )
        self.assertFalse((self.source_dir / "derived").exists())

    def test_not_activated_runtime_and_cli_create_nothing(self) -> None:
        state_parent = self.state_path.parent
        result = generate_shadow_evidence_checkpoints(
            state_path=self.state_path,
            output_dir=self.output_dir,
            generated_at=self.generated_at,
        )

        self.assertEqual("NOT_ACTIVATED", result["status"])
        self.assertEqual([], result["checkpoints"])
        self.assertFalse(state_parent.exists())
        self.assertFalse(self.output_dir.exists())

        output = io.StringIO()
        with patch("sys.stdout", output):
            exit_code = main(
                [
                    "--state-path",
                    str(self.state_path),
                    "--output-dir",
                    str(self.output_dir),
                ]
            )
        self.assertEqual(0, exit_code)
        self.assertEqual("NOT_ACTIVATED", json.loads(output.getvalue())["status"])
        self.assertFalse(state_parent.exists())
        self.assertFalse(self.output_dir.exists())

    def test_active_runtime_writes_checkpoint_without_mutating_sources(
        self,
    ) -> None:
        self._write_activation_and_state_source()
        state_before = self.state_path.read_bytes()
        activation_before = self.activation_path.read_bytes()

        with patch.object(
            ShadowTradingService,
            "snapshot",
            return_value=_snapshot(5, self.metadata),
        ):
            result = generate_shadow_evidence_checkpoints(
                state_path=self.state_path,
                output_dir=self.output_dir,
                generated_at=self.generated_at,
            )

        self.assertEqual("CHECKPOINTS_AVAILABLE", result["status"])
        self.assertEqual(1, len(result["checkpoints"]))
        self.assertTrue(result["checkpoints"][0]["created"])
        self.assertFalse(result["transmitting"])
        self.assertFalse(result["brokerRequestPerformed"])
        self.assertFalse(result["orderActionPerformed"])
        self.assertFalse(result["sourceStateMutated"])
        self.assertEqual(state_before, self.state_path.read_bytes())
        self.assertEqual(activation_before, self.activation_path.read_bytes())

    def test_concurrent_source_change_is_detected_after_write(self) -> None:
        self._write_activation_and_state_source()

        def mutate_source(payloads, *, output_dir):
            self.state_path.write_bytes(
                self.state_path.read_bytes() + b"changed"
            )
            return []

        with patch.object(
            ShadowTradingService,
            "snapshot",
            return_value=_snapshot(0, self.metadata),
        ), patch.object(
            checkpoint_module,
            "write_shadow_evidence_checkpoints",
            side_effect=mutate_source,
        ):
            with self.assertRaisesRegex(
                ShadowEvidenceCheckpointError,
                "source changed",
            ):
                generate_shadow_evidence_checkpoints(
                    state_path=self.state_path,
                    output_dir=self.output_dir,
                    generated_at=self.generated_at,
                )

    def test_module_has_no_network_broker_or_order_action_capability(self) -> None:
        source_path = Path(checkpoint_module.__file__)
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

    def _write_activation_and_state_source(self) -> None:
        self.source_dir.mkdir(parents=True)
        self.state_path.write_bytes(b"synthetic immutable state source")
        ShadowSampleActivationStore(self.activation_path).save_once(
            self.activation
        )


def _snapshot(
    count: int,
    metadata,
) -> dict:
    rows = [_review_row(index, metadata) for index in reversed(range(count))]
    meaningful = count >= MIN_MEANINGFUL_SAMPLE_SIZE
    metrics = {
        "sampleStatus": "MEANINGFUL" if meaningful else "INSUFFICIENT_SAMPLE",
        "minimumMeaningfulSample": MIN_MEANINGFUL_SAMPLE_SIZE,
        "candidateCount": count,
        "validTradePlanCount": count,
        "riskRejectedCount": 0,
        "simulatedEntryCount": count,
        "unfilledOrderCount": 0,
        "completedTradeCount": count,
        "winRatePercent": 60.0 if meaningful else None,
        "averageWin": 1.0 if meaningful else None,
        "averageLoss": -0.5 if meaningful else None,
        "expectancy": 0.4 if meaningful else None,
        "averageR": 0.8 if meaningful else None,
        "maximumDrawdown": -2.0 if meaningful else None,
        "profitFactor": 2.0 if meaningful else None,
        "idealPnl": 20.0 if meaningful else None,
        "executablePnl": 12.0 if meaningful else None,
        "idealVsExecutableGap": 8.0 if meaningful else None,
        "resultsBySetup": [],
        "resultsByCatalyst": [],
        "resultsByMarketRegime": [],
        "resultsByTimeOfDay": [],
        "conclusion": (
            "Sample supports descriptive aggregate evidence only."
            if meaningful
            else "Too few completed Shadow Trades for conclusions."
        ),
    }
    sample = {
        "minimumRequired": MIN_MEANINGFUL_SAMPLE_SIZE,
        "eligibleCompleted": count,
        "completed": count,
        "active": 0,
        "unfilled": 0,
        "riskRejected": 0,
        "dataQualityInvalidated": 0,
        "excluded": 0,
        "gateSatisfied": meaningful,
        "distinctTradingSessions": min(count, 10),
        "minimumDistinctSessionsForStrategyReview": 10,
        "strategyConclusionEligible": meaningful,
        "concentration": {},
        "sampleVersion": metadata.sample_version,
        "strategyConfigurationFingerprint": (
            metadata.strategy_configuration_fingerprint
        ),
        "fillModelVersion": metadata.fill_model_version,
        "evidenceSchemaVersion": metadata.evidence_schema_version,
        "officialSampleAuthorized": True,
        "readinessStatus": "PASS",
        "canStartOfficialSample": True,
        "readinessFindings": [],
        "status": "Synthetic canonical checkpoint snapshot.",
    }
    return {
        "schemaVersion": 1,
        "mode": SHADOW_MODE,
        "engineVersion": "shadow_trading_v1",
        "transmitting": False,
        "reviewTrades": rows,
        "sample": sample,
        "reviewMetrics": metrics,
    }


def _review_row(index: int, metadata) -> dict:
    decision = datetime.fromisoformat(
        "2026-08-03T10:00:00-05:00"
    ) + timedelta(days=index)
    return {
        "shadowTradeId": f"shadow-trade-{index:03d}",
        "symbol": f"T{index:03d}",
        "setup": "Synthetic setup",
        "catalyst": "Synthetic catalyst",
        "marketRegime": "risk_on",
        "session": "regular",
        "decisionTimestamp": decision.isoformat(),
        "evidenceSnapshotTimestamp": (
            decision - timedelta(minutes=2)
        ).isoformat(),
        "tradePlanId": f"trade-plan-{index:03d}",
        "riskDecisionId": f"risk-{index:03d}",
        "riskDecision": "APPROVED_FOR_SIMULATION",
        "riskReasons": [],
        "proposedEntry": 10.0,
        "simulatedFill": 10.01,
        "spreadPercent": 0.2,
        "slippageBps": 5.0,
        "stop": 9.5,
        "targets": [10.5],
        "exit": 10.5,
        "exitReason": "target_1",
        "idealPnl": 1.0,
        "executablePnl": 0.98,
        "rMultiple": 0.98,
        "mfeDollars": 1.1,
        "maeDollars": -0.1,
        "durationSeconds": 1800,
        "outcome": "WIN",
        "lifecycleState": "completed",
        "dataQualityState": "COMPLETE",
        "sampleMetadata": shadow_sample_metadata_to_dict(metadata),
        "lastReason": "Synthetic completed trade.",
        "evidenceLock": {
            "evidenceFrozen": True,
            "planFrozen": True,
            "decisionTimestamp": decision.isoformat(),
            "postDecisionCorrectionOccurred": False,
            "auditStatus": "PASS",
            "reasons": [],
        },
        "evidenceEligible": True,
        "countsTowardSample": True,
        "executionQuality": {
            "summary": "Synthetic execution evidence.",
            "factors": ["Synthetic execution evidence."],
            "technicalCodes": [],
        },
    }


if __name__ == "__main__":
    unittest.main()
