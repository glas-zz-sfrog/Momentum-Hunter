from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.workstation_read_models import (
    READ_ONLY_MODE_LABEL,
    WORKSTATION_SNAPSHOT_SCHEMA_VERSION,
    WorkstationReadModelPaths,
    build_read_only_workspace_snapshot,
)


class WorkstationReadModelTests(unittest.TestCase):
    def test_report_rows_are_mapped_without_recalculating_source_score_or_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_trade_report(paths.reports_dir / "trade-plan-briefing-2026-07-17-morning.json")
            write_monitor_status(paths.monitor_status_path)
            write_alerts(paths.alerts_path)

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual(WORKSTATION_SNAPSHOT_SCHEMA_VERSION, snapshot["schemaVersion"])
            self.assertEqual(READ_ONLY_MODE_LABEL, snapshot["mode"])
            candidate = self.assert_single(snapshot["candidates"])
            self.assertEqual("NVDA", candidate["symbol"])
            self.assertEqual(97, candidate["score"])
            self.assertEqual("PLANNING_SCAFFOLD", candidate["sourceReadinessLabel"])
            self.assertEqual("Persisted trade-planning report", candidate["dataLineage"]["sourceLabel"])
            self.assertFalse(snapshot["planningAvailable"])
            self.assertEqual("NOT_SELECTED", snapshot["replay"]["replayId"])
            self.assertIn("No candidate replay identity was synthesized", snapshot["replay"]["summary"])

    def test_missing_report_is_explicit_and_does_not_create_candidate_fallback_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual([], snapshot["candidates"])
            trade_report_health = next(item for item in snapshot["health"]["components"] if item["name"] == "Trade planning report")
            self.assertEqual("Unavailable", trade_report_health["state"])
            self.assertIn("no fallback data", trade_report_health["summary"].lower())
            self.assertEqual("UNAVAILABLE", snapshot["replay"]["replayId"])

    def test_missing_values_stay_explicitly_unavailable_in_quality_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_trade_report(paths.reports_dir / "trade-plan-briefing-2026-07-17-morning.json", last_price=None, rvol=None)

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            candidate = self.assert_single(snapshot["candidates"])
            self.assertIsNone(candidate["lastPrice"])
            self.assertIsNone(candidate["relativeVolume"])
            self.assertIn("last price unavailable", candidate["qualityLabel"])
            self.assertIn("relative volume unavailable", candidate["qualityLabel"])

    def test_read_model_builder_does_not_mutate_persisted_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            report_path = paths.reports_dir / "trade-plan-briefing-2026-07-17-morning.json"
            write_trade_report(report_path)
            before = sha256(report_path)

            build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual(before, sha256(report_path))
            self.assertEqual([report_path], list(paths.reports_dir.glob("*.json")))

    @staticmethod
    def assert_single(values: list[object]) -> dict:
        if len(values) != 1:
            raise AssertionError(f"Expected one value, found {len(values)}")
        value = values[0]
        if not isinstance(value, dict):
            raise AssertionError("Expected a mapping")
        return value


def make_paths(root: Path) -> WorkstationReadModelPaths:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True)
    return WorkstationReadModelPaths(
        data_dir=data_dir,
        reports_dir=reports_dir,
        monitor_status_path=data_dir / "active-monitor-status.json",
        alerts_path=data_dir / "opportunity-alerts.json",
    )


def write_trade_report(path: Path, *, last_price: float | None = 176.42, rvol: float | None = 2.4) -> None:
    payload = {
        "schema_version": 1,
        "metadata": {
            "generated_at": "2026-07-17T09:30:00-05:00",
            "source_capture_path": "MomentumHunterData/data/captures/2026-07-17/morning.json",
            "source_capture_time": "2026-07-17T09:25:00-05:00",
        },
        "candidates": [
            {
                "symbol": "NVDA",
                "company": "NVIDIA Corporation",
                "market_data": {
                    "last_price": last_price,
                    "premarket_percent": 3.18,
                    "intraday_volume": 84700112,
                    "relative_volume": rvol,
                    "spread_percent": 0.12,
                },
                "scoring": {"composite_score": 97, "catalyst_summary": "Stored catalyst"},
                "trade_plan": {"readiness": "PLANNING_SCAFFOLD"},
                "opportunity_notes": ["Stored note"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_monitor_status(path: Path) -> None:
    payload = {
        "state": "IDLE",
        "started_at": "2026-07-17T09:00:00-05:00",
        "updated_at": "2026-07-17T09:31:00-05:00",
        "cycles_requested": 1,
        "cycles_completed": 1,
        "warnings": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_alerts(path: Path) -> None:
    path.write_text(json.dumps({"alerts": [{"outcome": {"status": "PENDING_OUTCOME"}}]}), encoding="utf-8")


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
