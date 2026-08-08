from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.engine_host import (
    COMMAND_RUN_SIMULATION,
    COMMAND_SIMULATION_WORKSPACE_SNAPSHOT,
    EngineHostRuntime,
)
from momentum_hunter.workstation_read_models import WorkstationReadModelPaths
from momentum_hunter.workstation_simulation import (
    SIMULATION_WORKSPACE_MODE,
    SIMULATION_WORKSPACE_SCHEMA_VERSION,
    SimulationWorkspaceService,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.trade_setup_identity import TradeSetupEvidence


class SimulationWorkspaceServiceTests(unittest.TestCase):
    def test_snapshot_rehydrates_persisted_plan_without_mutating_source_or_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, report_path = setup_workspace(Path(directory))
            before = sha256(report_path)

            snapshot = SimulationWorkspaceService(paths=paths).snapshot(observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual(SIMULATION_WORKSPACE_SCHEMA_VERSION, snapshot["schemaVersion"])
            self.assertEqual(SIMULATION_WORKSPACE_MODE, snapshot["mode"])
            self.assertTrue(snapshot["planningAvailable"])
            plan = assert_single(snapshot["plans"])
            self.assertEqual("NVDA", plan["symbol"])
            self.assertEqual(176.42, plan["entry"])
            self.assertTrue(plan["risk"]["allowsSimulation"])
            self.assertEqual(97, assert_single(snapshot["workspace"]["candidates"])["score"])
            self.assertEqual(before, sha256(report_path))

    def test_snapshot_rehydrates_each_persisted_candidate_plan_not_only_top_five(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, report_path = setup_workspace(Path(directory), additional_candidates=[candidate_row(symbol="AMD")])
            before = sha256(report_path)

            snapshot = SimulationWorkspaceService(paths=paths).snapshot()

            plans_by_symbol = {plan["symbol"]: plan for plan in snapshot["plans"]}
            self.assertEqual({"NVDA", "AMD"}, set(plans_by_symbol))
            self.assertEqual(176.42, plans_by_symbol["NVDA"]["entry"])
            self.assertEqual(176.42, plans_by_symbol["AMD"]["entry"])
            self.assertEqual(before, sha256(report_path))

    def test_completed_simulation_records_risk_preview_submit_and_passing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = setup_workspace(Path(directory))
            service = SimulationWorkspaceService(paths=paths)

            with patch(
                "momentum_hunter.autonomy.risk_governor.now_central",
                return_value=datetime.fromisoformat("2026-07-17T10:00:00-05:00"),
            ):
                result = service.run_simulation("nvda")

            self.assertEqual("Completed", result["state"])
            self.assertEqual("NVDA", result["symbol"])
            self.assertTrue(result["audit"]["passed"])
            self.assertEqual("FakeBrokerAdapter", result["ledgerEvents"][-1]["broker_adapter"])
            actions = {event["requested_action"] for event in result["ledgerEvents"]}
            self.assertEqual({"risk_gate_evaluated", "simulated_order_previewed", "fake_order_submitted"}, actions)

    def test_blocked_plan_records_risk_then_block_without_fake_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = setup_workspace(Path(directory), stop=None)
            result = SimulationWorkspaceService(paths=paths).run_simulation("NVDA")

            self.assertEqual("Blocked", result["state"])
            self.assertTrue(result["audit"]["passed"])
            actions = {event["requested_action"] for event in result["ledgerEvents"]}
            self.assertIn("risk_gate_evaluated", actions)
            self.assertIn("simulation_blocked", actions)
            self.assertNotIn("simulated_order_previewed", actions)
            self.assertNotIn("fake_order_submitted", actions)

    def test_unknown_symbol_is_unavailable_without_creating_ledger_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = setup_workspace(Path(directory))
            result = SimulationWorkspaceService(paths=paths).run_simulation("MSTR")

            self.assertEqual("Unavailable", result["state"])
            self.assertEqual([], result["ledgerEvents"])


class SimulationHostCommandTests(unittest.TestCase):
    def test_simulation_host_commands_require_symbol_and_reject_command_id_reuse(self) -> None:
        calls: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            simulation_workspace_loader=lambda: {"schemaVersion": 1, "mode": SIMULATION_WORKSPACE_MODE},
            simulation_runner=lambda symbol: calls.append(symbol) or {"mode": SIMULATION_WORKSPACE_MODE, "symbol": symbol},
        )

        snapshot = runtime.execute(COMMAND_SIMULATION_WORKSPACE_SNAPSHOT, "simulation-snapshot")
        missing_symbol = runtime.execute(COMMAND_RUN_SIMULATION, "simulation-missing")
        completed = runtime.execute(COMMAND_RUN_SIMULATION, "simulation-nvda", {"symbol": "nvda"})
        repeated = runtime.execute(COMMAND_RUN_SIMULATION, "simulation-nvda", {"symbol": "nvda"})
        reused = runtime.execute(COMMAND_RUN_SIMULATION, "simulation-nvda", {"symbol": "mstr"})

        self.assertTrue(snapshot.accepted)
        self.assertEqual("SIMULATION_WORKSPACE_SNAPSHOT", snapshot.code)
        self.assertFalse(missing_symbol.accepted)
        self.assertEqual("SIMULATION_SYMBOL_REQUIRED", missing_symbol.code)
        self.assertTrue(completed.accepted)
        self.assertEqual(completed, repeated)
        self.assertEqual(["NVDA"], calls)
        self.assertFalse(reused.accepted)
        self.assertEqual("COMMAND_ID_REUSED", reused.code)


def setup_workspace(
    root: Path,
    *,
    stop: float | None = 171.42,
    additional_candidates: list[dict] | None = None,
) -> tuple[WorkstationReadModelPaths, Path]:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True)
    paths = WorkstationReadModelPaths(
        data_dir=data_dir,
        reports_dir=reports_dir,
        monitor_status_path=data_dir / "active-monitor-status.json",
        alerts_path=data_dir / "opportunity-alerts.json",
    )
    report_path = reports_dir / "trade-plan-briefing-2026-07-17-morning.json"
    report_path.write_text(json.dumps(report_payload(stop=stop, additional_candidates=additional_candidates)), encoding="utf-8")
    return paths, report_path


def report_payload(*, stop: float | None, additional_candidates: list[dict] | None = None) -> dict:
    primary_candidate = candidate_row(stop=stop)
    return {
        "schema_version": 1,
        "metadata": {
            "generated_at": "2026-07-17T09:30:00-05:00",
            "source_capture_path": "MomentumHunterData/data/captures/2026-07-17/morning.json",
            "source_capture_time": "2026-07-17T09:25:00-05:00",
        },
        "top_5_for_capital": [primary_candidate],
        "candidates": [primary_candidate, *(additional_candidates or [])],
    }


def candidate_row(*, stop: float | None = 171.42, symbol: str = "NVDA") -> dict:
    setup = TradeSetupEvidence(fingerprint="a" * 64)
    intraday = build_intraday_plan_evidence(
        symbol=symbol,
        setup_family=CONTINUATION_BREAKOUT,
        created_at=datetime.fromisoformat("2026-07-17T09:30:00-05:00"),
        planned_entry=176.42,
        stop_price=stop if stop is not None else 171.42,
        target_prices=(186.42, 191.42),
        source_setup_fingerprint=setup.fingerprint,
        source_level_kind="SYNTHETIC_CONTINUATION_RANGE",
        source_evidence_ids=("synthetic-candle-range",),
    )
    return {
        "symbol": symbol,
        "company": "NVIDIA Corporation",
        "market_data": {
            "last_price": 176.42,
            "premarket_percent": 3.18,
            "intraday_volume": 84700112,
            "relative_volume": 2.4,
            "spread_percent": 0.12,
        },
        "scoring": {"composite_score": 97, "catalyst_summary": "Stored catalyst"},
        "trade_plan": {
            "bullish_entry": 176.42,
            "bullish_stop": stop,
            "bullish_target_1": 186.42,
            "bullish_target_2": 191.42,
            "risk_reward_ratio": 2.0,
            "estimated_shares_for_500": 2.833,
            "estimated_dollar_risk": 14.17 if stop is not None else None,
            "estimated_target_1_reward": 28.33,
            "confidence": "MEDIUM",
            "tradeability": "MEDIUM",
            "readiness": "EXECUTION_READY_TRADE",
            "blocking_reasons": [],
            "warnings": [],
            "setup_evidence": asdict(setup),
            "intraday_evidence": asdict(intraday),
        },
        "opportunity_notes": ["Stored note"],
    }


def assert_single(values: list[object]) -> dict:
    if len(values) != 1 or not isinstance(values[0], dict):
        raise AssertionError(f"Expected one mapping, found {len(values)} values")
    return values[0]


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
