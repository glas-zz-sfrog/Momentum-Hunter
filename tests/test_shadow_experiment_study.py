from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.shadow_experiment_study as study_module
from momentum_hunter.shadow_experiment_study import (
    SHADOW_EXPERIMENT_STUDY_MODE,
    ShadowExperimentStudyError,
    build_shadow_experiment_study,
    generate_shadow_experiment_study,
)
from momentum_hunter.shadow_trade_experiments import (
    SHADOW_TRADE_EXPERIMENT_ENGINE_VERSION,
    SHADOW_TRADE_EXPERIMENT_MODE,
    SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION,
    ShadowTradeExperimentError,
    load_shadow_trade_experiment,
    write_shadow_trade_experiment,
)
from momentum_hunter.shadow_trading import canonical_json, stable_id


class ShadowExperimentStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.experiments_dir = self.root / "experiments"
        self.output_dir = self.root / "studies"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_below_thirty_withholds_all_performance_and_lift_metrics(
        self,
    ) -> None:
        experiments = [_experiment(index) for index in range(5)]

        study = _build(experiments)

        self.assertFalse(study["sample_gate"]["gate_satisfied"])
        self.assertEqual(
            "WITHHELD_BELOW_30",
            study["sample_gate"]["metrics_status"],
        )
        self.assertFalse(
            study["sample_gate"]["strategy_review_eligible"]
        )
        self.assertEqual(5, study["selected_results"]["completed_count"])
        self.assertTrue(
            all(
                value is None
                for name, value in study["selected_results"].items()
                if name != "completed_count"
            )
        )
        for comparison in study[
            "paired_counterfactual_comparisons"
        ].values():
            self.assertEqual(5, comparison["paired_count"])
            self.assertTrue(
                all(
                    value is None
                    for name, value in comparison.items()
                    if name != "paired_count"
                )
            )
        self.assertFalse(
            study["sample_gate"]["strategy_conclusion_authorized"]
        )
        self.assertFalse(study["sample_gate"]["trading_authorized"])

    def test_thirty_trades_across_ten_sessions_release_descriptive_pairs(
        self,
    ) -> None:
        experiments = [
            _experiment(
                index,
                trading_day=date(2026, 7, 6) + timedelta(days=index % 10),
                selected_return=1.0 + index / 100,
                random_return=0.50,
                other_return=0.25,
                spy_return=0.10,
                iwm_return=0.20,
            )
            for index in range(30)
        ]

        study = _build(experiments)

        gate = study["sample_gate"]
        self.assertTrue(gate["gate_satisfied"])
        self.assertEqual("DESCRIPTIVE_AVAILABLE", gate["metrics_status"])
        self.assertEqual(10, gate["distinct_trading_sessions"])
        self.assertTrue(gate["strategy_review_eligible"])
        self.assertFalse(gate["strategy_conclusion_authorized"])
        self.assertFalse(gate["trading_authorized"])
        selected = study["selected_results"]
        self.assertEqual(30, selected["completed_count"])
        self.assertEqual(100.0, selected["win_rate_percent"])
        self.assertIsNotNone(selected["mean_r_multiple"])
        comparisons = study["paired_counterfactual_comparisons"]
        self.assertEqual(
            30,
            comparisons["DETERMINISTIC_RANDOM_ELIGIBLE"][
                "paired_count"
            ],
        )
        self.assertGreater(
            comparisons["DETERMINISTIC_RANDOM_ELIGIBLE"][
                "mean_lift_percentage_points"
            ],
            0,
        )
        self.assertGreater(
            comparisons["SPY"]["mean_lift_percentage_points"],
            0,
        )
        self.assertIn(
            "does not prove durable edge",
            study["conclusion"],
        )

    def test_thirty_trades_on_too_few_sessions_still_block_review(
        self,
    ) -> None:
        experiments = [
            _experiment(index, trading_day=date(2026, 7, 6))
            for index in range(30)
        ]

        study = _build(experiments)

        self.assertTrue(study["sample_gate"]["gate_satisfied"])
        self.assertEqual(
            "DESCRIPTIVE_AVAILABLE",
            study["sample_gate"]["metrics_status"],
        )
        self.assertEqual(
            1,
            study["sample_gate"]["distinct_trading_sessions"],
        )
        self.assertFalse(
            study["sample_gate"]["strategy_review_eligible"]
        )
        self.assertIn(
            "broader strategy review remains blocked",
            study["conclusion"],
        )

    def test_unavailable_benchmark_marks_reduce_pairs_without_zero_fill(
        self,
    ) -> None:
        experiments = [_experiment(index) for index in range(30)]
        for experiment in experiments[:5]:
            spy = next(
                mark
                for mark in experiment["selection_experiment"][
                    "counterfactual_marks"
                ]
                if mark["symbol"] == "SPY"
            )
            spy["available"] = False
            spy["return_percent"] = None

        study = _build(experiments)

        spy_comparison = study[
            "paired_counterfactual_comparisons"
        ]["SPY"]
        self.assertEqual(25, spy_comparison["paired_count"])
        self.assertEqual(
            0.1,
            spy_comparison["mean_comparison_return_percent"],
        )
        self.assertEqual(
            25,
            study["availability"]["available_mark_counts"]["SPY"],
        )

    def test_multiple_eligible_sample_versions_fail_without_selection(
        self,
    ) -> None:
        experiments = [
            *[_experiment(index) for index in range(30)],
            _experiment(31, sample_version="official-shadow-v2"),
        ]

        with self.assertRaisesRegex(
            ShadowExperimentStudyError,
            "multiple official sample versions",
        ):
            _build(experiments)

        selected = _build(
            experiments,
            sample_version="official-shadow-v1",
        )
        self.assertEqual(
            30,
            selected["collection"]["eligible_completed_count"],
        )
        self.assertEqual(
            1,
            selected["collection"]["excluded_other_sample_count"],
        )

    def test_final_snapshot_supersedes_pending_snapshot_for_same_trade(
        self,
    ) -> None:
        final = _experiment(1)
        pending = _experiment(
            1,
            artifact_status="PENDING_OR_UNFILLED",
            counts_toward_sample=False,
            outcome=None,
            snapshot_suffix="pending",
        )

        study = _build([pending, final])

        self.assertEqual(2, study["collection"]["artifact_count"])
        self.assertEqual(1, study["collection"]["unique_trade_count"])
        self.assertEqual(
            1,
            study["collection"]["superseded_snapshot_count"],
        )
        self.assertEqual(
            1,
            study["collection"]["eligible_completed_count"],
        )

    def test_equivalent_final_snapshots_are_safely_superseded(
        self,
    ) -> None:
        first = _experiment(1, snapshot_suffix="first")
        second = _experiment(1, snapshot_suffix="second")

        study = _build([first, second])

        self.assertEqual(1, study["collection"]["unique_trade_count"])
        self.assertEqual(
            1,
            study["collection"]["superseded_snapshot_count"],
        )

    def test_conflicting_final_snapshots_for_one_trade_fail_closed(
        self,
    ) -> None:
        first = _experiment(1, snapshot_suffix="first")
        second = _experiment(1, snapshot_suffix="second")
        second["outcome"]["executable_pnl"] = 999.0

        with self.assertRaisesRegex(
            ShadowExperimentStudyError,
            "conflicting final experiment",
        ):
            _build([first, second])

    def test_generation_is_strict_nonmutating_and_idempotent(self) -> None:
        writes = [
            write_shadow_trade_experiment(
                _experiment(
                    index,
                    trading_day=(
                        date(2026, 7, 6) + timedelta(days=index % 10)
                    ),
                ),
                output_dir=self.experiments_dir,
            )
            for index in range(30)
        ]
        source_before = {
            item.json_path: item.json_path.read_bytes() for item in writes
        }

        first = generate_shadow_experiment_study(
            experiments_dir=self.experiments_dir,
            output_dir=self.output_dir,
        )
        repeated = generate_shadow_experiment_study(
            experiments_dir=self.experiments_dir,
            output_dir=self.output_dir,
        )

        self.assertTrue(first.created)
        self.assertFalse(repeated.created)
        self.assertEqual(first.study_id, repeated.study_id)
        self.assertTrue(first.source_artifacts_unchanged)
        self.assertEqual(
            source_before,
            {
                path: path.read_bytes() for path in source_before
            },
        )
        study = _study(first.json_path)
        self.assertEqual(SHADOW_EXPERIMENT_STUDY_MODE, study["mode"])
        self.assertEqual(30, study["sample_gate"]["eligible_completed"])
        self.assertFalse(study["transmitting"])
        self.assertFalse(study["broker_request_performed"])
        self.assertFalse(study["order_action_performed"])
        markdown = first.markdown_path.read_text(encoding="utf-8")
        self.assertIn("Strategy conclusion authorized: no", markdown)
        self.assertIn("Trading authorized: no", markdown)

    def test_tampered_or_renamed_experiment_artifact_fails_closed(
        self,
    ) -> None:
        write = write_shadow_trade_experiment(
            _experiment(1),
            output_dir=self.experiments_dir,
        )
        renamed = write.json_path.with_name(f"renamed-{write.json_path.name}")
        renamed.write_bytes(write.json_path.read_bytes())
        with self.assertRaisesRegex(
            ShadowTradeExperimentError,
            "filename",
        ):
            load_shadow_trade_experiment(renamed)
        renamed.unlink()

        payload = json.loads(write.json_path.read_text(encoding="utf-8"))
        payload["experiment"]["candidate"]["score"] = 999
        write.json_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            ShadowExperimentStudyError,
            "Invalid Shadow experiment",
        ):
            generate_shadow_experiment_study(
                experiments_dir=self.experiments_dir,
                output_dir=self.output_dir,
            )

    def test_concurrent_source_change_is_detected_after_study_write(
        self,
    ) -> None:
        write_shadow_trade_experiment(
            _experiment(1),
            output_dir=self.experiments_dir,
        )
        source_path = next(self.experiments_dir.glob("*.json"))
        original_write = study_module.write_shadow_experiment_study

        def mutate_after_write(study, *, output_dir):
            result = original_write(study, output_dir=output_dir)
            source_path.write_bytes(source_path.read_bytes() + b"\n")
            return result

        with patch.object(
            study_module,
            "write_shadow_experiment_study",
            side_effect=mutate_after_write,
        ), self.assertRaisesRegex(
            ShadowExperimentStudyError,
            "source changed",
        ):
            generate_shadow_experiment_study(
                experiments_dir=self.experiments_dir,
                output_dir=self.output_dir,
            )

    def test_conflicting_existing_study_is_preserved_and_rejected(
        self,
    ) -> None:
        write_shadow_trade_experiment(
            _experiment(1),
            output_dir=self.experiments_dir,
        )
        first = generate_shadow_experiment_study(
            experiments_dir=self.experiments_dir,
            output_dir=self.output_dir,
        )
        first.markdown_path.write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(
            ShadowExperimentStudyError,
            "conflicts",
        ):
            generate_shadow_experiment_study(
                experiments_dir=self.experiments_dir,
                output_dir=self.output_dir,
            )

    def test_empty_directory_produces_truthful_withheld_study(self) -> None:
        self.experiments_dir.mkdir()

        result = generate_shadow_experiment_study(
            experiments_dir=self.experiments_dir,
            output_dir=self.output_dir,
        )

        study = _study(result.json_path)
        self.assertIsNone(study["sample_version"])
        self.assertEqual(0, study["collection"]["artifact_count"])
        self.assertEqual(
            "WITHHELD_BELOW_30",
            study["sample_gate"]["metrics_status"],
        )

    def test_study_module_has_no_provider_broker_or_strategy_mutation_surface(
        self,
    ) -> None:
        source = Path(study_module.__file__).read_text(encoding="utf-8")
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
        self.assertIn(SHADOW_EXPERIMENT_STUDY_MODE, source)


def _build(
    experiments: list[dict],
    *,
    sample_version: str | None = None,
) -> dict:
    return build_shadow_experiment_study(
        experiments,
        source_manifest=[
            {
                "path": f"C:/synthetic/{item['experiment_id']}.json",
                "sha256": hashlib.sha256(
                    item["experiment_id"].encode("utf-8")
                ).hexdigest(),
                "experiment_id": item["experiment_id"],
                "shadow_trade_id": item["identity"]["shadow_trade_id"],
            }
            for item in experiments
        ],
        sample_version=sample_version,
    )


def _experiment(
    index: int,
    *,
    trading_day: date = date(2026, 7, 6),
    sample_version: str = "official-shadow-v1",
    selected_return: float = 1.0,
    random_return: float = 0.5,
    other_return: float = 0.25,
    spy_return: float = 0.1,
    iwm_return: float = 0.2,
    artifact_status: str = "COMPLETE",
    counts_toward_sample: bool = True,
    outcome: dict | None | object = ...,
    snapshot_suffix: str = "final",
) -> dict:
    trade_id = f"shadow-trade-synthetic-{index:03d}"
    decision = datetime(
        trading_day.year,
        trading_day.month,
        trading_day.day,
        10,
        0,
        tzinfo=timezone(timedelta(hours=-5)),
    )
    exit_at = decision + timedelta(minutes=30)
    if outcome is ...:
        outcome = {
            "outcome_id": f"shadow-outcome-synthetic-{index:03d}",
            "shadow_trade_id": trade_id,
            "status": "COMPLETED",
            "classification": "WIN",
            "exit_timestamp": exit_at.isoformat(),
            "exit_reason": "target_1",
            "exit_price": 10.5,
            "gross_pnl": 1.10,
            "executable_pnl": 1.00,
            "r_multiple": 1.0,
            "mfe_dollars": 1.20,
            "mae_dollars": -0.20,
            "mfe_percent": 2.0,
            "mae_percent": -0.5,
            "duration_seconds": 1800,
        }
    marks = [
        _mark(
            f"SEL{index:03d}",
            ("SELECTED",),
            selected_return,
        ),
        _mark(
            f"RND{index:03d}",
            ("DETERMINISTIC_RANDOM_ELIGIBLE",),
            random_return,
        ),
        _mark(
            f"OTH{index:03d}",
            ("OTHER_ELIGIBLE",),
            other_return,
        ),
        _mark("SPY", ("BENCHMARK",), spy_return),
        _mark("IWM", ("BENCHMARK",), iwm_return),
    ]
    core = {
        "schema_version": SHADOW_TRADE_EXPERIMENT_SCHEMA_VERSION,
        "engine_version": SHADOW_TRADE_EXPERIMENT_ENGINE_VERSION,
        "mode": SHADOW_TRADE_EXPERIMENT_MODE,
        "transmitting": False,
        "broker_request_performed": False,
        "order_action_performed": False,
        "artifact_status": artifact_status,
        "identity": {
            "shadow_trade_id": trade_id,
            "simulation_command_id": f"command-{index:03d}",
            "candidate_id": f"candidate-{index:03d}",
            "evidence_snapshot_id": f"evidence-{index:03d}",
            "trade_plan_id": f"plan-{index:03d}",
            "risk_decision_id": f"risk-{index:03d}",
            "outcome_id": f"shadow-outcome-synthetic-{index:03d}",
            "decision_cycle_id": f"cycle-{index:03d}",
            "opportunity_id": f"opportunity-{index:03d}",
        },
        "source_evidence": {
            "state_path": "C:/synthetic/state.json",
            "state_sha256": "a" * 64,
        },
        "sample_definition": {
            "sampleVersion": sample_version,
            "strategyConfigurationFingerprint": "b" * 64,
            "fillModelVersion": "prospective-fakebroker-v1",
            "evidenceSchemaVersion": 1,
            "officialSampleAuthorized": True,
        },
        "candidate": {
            "symbol": f"SYM{index:03d}",
            "rank": 1,
            "score": 90.0,
            "setup": "Synthetic setup",
            "catalyst": "Synthetic catalyst",
            "market_regime": "risk_on",
            "decision_timestamp": decision.isoformat(),
            "frozen_payload": {},
        },
        "selection_experiment": {
            "evidence_status": "PASS",
            "cycle_id": f"cycle-{index:03d}",
            "cycle_status": "TRADE_STARTED",
            "eligible_candidate_count": 3,
            "candidate_assessments": [],
            "counterfactual_status": (
                "FINALIZED_TO_SELECTED_TRADE_EXIT"
                if artifact_status == "COMPLETE"
                else "MARK_TO_LATEST"
            ),
            "counterfactual_marks": marks,
        },
        "trade_plan": {},
        "risk_governor": {"status": "PASS"},
        "execution": {
            "lifecycle_state": (
                "completed"
                if artifact_status == "COMPLETE"
                else "pending_entry"
            ),
            "data_quality_state": "COMPLETE",
            "ledger_events": [],
            "last_observation_timestamp": (
                exit_at.isoformat()
                if artifact_status == "COMPLETE"
                else decision.isoformat()
            ),
            "last_reason": "",
        },
        "outcome": outcome,
        "paper_money_reconciliation": {
            "evidence_status": "NOT_RECORDED"
        },
        "review_projection": {
            "countsTowardSample": counts_toward_sample,
            "riskDecision": "PASS",
            "proposedEntry": 10.0,
            "stop": 9.5,
            "targets": [10.5],
            "simulatedFill": 9.96,
            "exit": 10.5 if outcome else None,
            "exitReason": "target_1" if outcome else "",
            "outcome": "WIN" if outcome else "UNFILLED",
            "executablePnl": (
                outcome["executable_pnl"] if outcome else None
            ),
            "idealPnl": outcome["gross_pnl"] if outcome else None,
            "rMultiple": outcome["r_multiple"] if outcome else None,
            "mfeDollars": outcome["mfe_dollars"] if outcome else None,
            "maeDollars": outcome["mae_dollars"] if outcome else None,
            "durationSeconds": (
                outcome["duration_seconds"] if outcome else None
            ),
        },
        "integrity": {
            "status": "PASS",
            "findings": [],
            "source_state_mutated": False,
        },
        "research_limits": {
            "counts_toward_official_sample": counts_toward_sample,
            "single_trade_strategy_conclusion_authorized": False,
            "trading_authorized": False,
            "conclusion": "Synthetic test evidence only.",
        },
    }
    fingerprint = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    experiment_id = stable_id(
        "shadow-trade-experiment",
        trade_id,
        fingerprint,
    )
    if snapshot_suffix != "final":
        core["source_evidence"]["snapshot_suffix"] = snapshot_suffix
        fingerprint = hashlib.sha256(
            canonical_json(core).encode("utf-8")
        ).hexdigest()
        experiment_id = stable_id(
            "shadow-trade-experiment",
            trade_id,
            fingerprint,
        )
    return {
        "experiment_id": experiment_id,
        "experiment_fingerprint": fingerprint,
        **core,
    }


def _mark(
    symbol: str,
    roles: tuple[str, ...],
    return_percent: float,
) -> dict:
    return {
        "symbol": symbol,
        "roles": list(roles),
        "baseline_timestamp": "2026-07-06T10:00:00-05:00",
        "baseline_price": 10.0,
        "baseline_available": True,
        "latest_timestamp": "2026-07-06T10:30:00-05:00",
        "latest_price": 10.0 * (1 + return_percent / 100),
        "return_percent": return_percent,
        "observation_count": 1,
        "available": True,
        "measurement": "SELECTED_TRADE_HOLDING_WINDOW",
    }


def _study(path: Path) -> dict:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    study = envelope["study"]
    expected = hashlib.sha256(
        canonical_json(study).encode("utf-8")
    ).hexdigest()
    if envelope["study_sha256"] != expected:
        raise AssertionError("Study envelope hash does not match.")
    return study


if __name__ == "__main__":
    unittest.main()
