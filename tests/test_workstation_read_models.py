from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
            self.assertEqual(["Stored note"], candidate["notes"])
            self.assertFalse(snapshot["planningAvailable"])
            self.assertEqual("NOT_SELECTED", snapshot["replay"]["replayId"])
            self.assertIn("No candidate replay identity was synthesized", snapshot["replay"]["summary"])
            self.assertEqual("AVAILABLE", snapshot["alertEvidence"]["state"])

    def test_missing_report_is_explicit_and_does_not_create_candidate_fallback_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual([], snapshot["candidates"])
            trade_report_health = next(item for item in snapshot["health"]["components"] if item["name"] == "Trade planning report")
            self.assertEqual("Unavailable", trade_report_health["state"])
            self.assertIn("no fallback data", trade_report_health["summary"].lower())
            self.assertEqual("UNAVAILABLE", snapshot["replay"]["replayId"])
            self.assertEqual("UNAVAILABLE", snapshot["alertEvidence"]["state"])

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
            write_alerts(paths.alerts_path)
            report_before = sha256(report_path)
            alerts_before = sha256(paths.alerts_path)

            build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            self.assertEqual(report_before, sha256(report_path))
            self.assertEqual(alerts_before, sha256(paths.alerts_path))
            self.assertEqual([report_path], list(paths.reports_dir.glob("*.json")))

    def test_alert_evidence_preserves_stored_states_outcomes_and_missing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            write_alert_evidence(paths.alerts_path)

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            evidence = snapshot["alertEvidence"]
            self.assertEqual("AVAILABLE", evidence["state"])
            self.assertEqual(3, evidence["totalAlertCount"])
            self.assertEqual(1, evidence["activeAlertCount"])
            self.assertEqual(2, evidence["recordedOutcomeCount"])
            self.assertEqual(1, evidence["unscorableOutcomeCount"])
            active = self.assert_single(evidence["activeAlerts"])
            self.assertEqual("alert-active", active["alertId"])
            self.assertEqual("NVDA", active["symbol"])
            self.assertEqual("BREAKOUT", active["alertType"])
            self.assertEqual("ACTIVE", active["state"])
            self.assertEqual("Range breakout persisted.", active["summary"])
            self.assertEqual("2026-07-17T14:35:00Z", active["timestamp"])
            self.assertEqual(["alert-complete", ""], [row["alertId"] for row in evidence["outcomes"]])
            completed = evidence["outcomes"][0]
            self.assertEqual("COMPLETED", completed["status"])
            self.assertEqual("SUCCESSFUL", completed["classification"])
            self.assertIn("60m +4.25%", completed["summary"])
            self.assertIn("target 1 hit", completed["summary"])
            self.assertIsNone(evidence["outcomes"][1]["alertTimestamp"])

    def test_readable_empty_alert_store_is_not_reported_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            paths.alerts_path.write_text(json.dumps({"alerts": []}), encoding="utf-8")

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            evidence = snapshot["alertEvidence"]
            self.assertEqual("EMPTY", evidence["state"])
            self.assertEqual([], evidence["activeAlerts"])
            self.assertEqual([], evidence["outcomes"])
            self.assertIn("no alerts", evidence["summary"].lower())
            self.assertIn("no analytics or classifications were inferred", evidence["summary"].lower())

    def test_malformed_alert_store_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            paths.alerts_path.write_text("{bad json", encoding="utf-8")

            snapshot = build_read_only_workspace_snapshot(paths=paths, observed_at=at("2026-07-17T15:00:00Z"))

            evidence = snapshot["alertEvidence"]
            self.assertEqual("UNAVAILABLE", evidence["state"])
            self.assertEqual([], evidence["activeAlerts"])
            self.assertEqual([], evidence["outcomes"])

    def test_structurally_invalid_alert_collection_is_not_reported_as_empty(self) -> None:
        for payload in ({}, {"alerts": {}}, {"alerts": [{"alert_id": "valid"}, "invalid-row"]}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                paths = make_paths(Path(directory))
                paths.alerts_path.write_text(json.dumps(payload), encoding="utf-8")

                snapshot = build_read_only_workspace_snapshot(
                    paths=paths,
                    observed_at=at("2026-07-17T15:00:00Z"),
                )

                evidence = snapshot["alertEvidence"]
                self.assertEqual("UNAVAILABLE", evidence["state"])
                self.assertEqual(0, evidence["totalAlertCount"])
                self.assertEqual([], evidence["activeAlerts"])
                self.assertEqual([], evidence["outcomes"])
                self.assertIn("structurally invalid", evidence["summary"].lower())

    def test_alert_row_limits_do_not_change_full_store_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            start = at("2026-07-17T12:00:00Z")
            alerts = []
            for index in range(55):
                alerts.append(
                    {
                        "alert_id": f"active-{index:03d}",
                        "symbol": "NVDA",
                        "timestamp": (start + timedelta(minutes=index)).isoformat(),
                        "outcome": {"status": "ACTIVE", "classification": "PENDING"},
                    }
                )
            for index in range(105):
                alerts.append(
                    {
                        "alert_id": f"outcome-{index:03d}",
                        "symbol": "CRWD",
                        "timestamp": (start + timedelta(minutes=1000 + index)).isoformat(),
                        "outcome": {"status": "COMPLETED", "classification": "SUCCESSFUL"},
                    }
                )
            paths.alerts_path.write_text(json.dumps({"alerts": alerts}), encoding="utf-8")

            evidence = build_read_only_workspace_snapshot(
                paths=paths,
                observed_at=at("2026-07-17T15:00:00Z"),
            )["alertEvidence"]

            self.assertEqual(160, evidence["totalAlertCount"])
            self.assertEqual(55, evidence["activeAlertCount"])
            self.assertEqual(105, evidence["recordedOutcomeCount"])
            self.assertEqual(50, len(evidence["activeAlerts"]))
            self.assertEqual(100, len(evidence["outcomes"]))
            self.assertEqual("active-054", evidence["activeAlerts"][0]["alertId"])
            self.assertEqual("outcome-104", evidence["outcomes"][0]["alertId"])
            self.assertIn("Counts cover the full store", evidence["summary"])

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


def write_alert_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "alerts": [
                    {
                        "alert_id": "alert-complete",
                        "symbol": "CRWD",
                        "timestamp": "2026-07-17T14:30:00Z",
                        "alert_type": "MOMENTUM",
                        "current_state": "READY",
                        "reason": "Stored completed alert.",
                        "outcome": {
                            "status": "COMPLETED",
                            "classification": "SUCCESSFUL",
                            "sixty_minute_return_pct": 4.25,
                            "target_1_hit": True,
                            "stop_hit": False,
                        },
                    },
                    {
                        "alert_id": "alert-active",
                        "symbol": "nvda",
                        "timestamp": "2026-07-17T14:35:00Z",
                        "alert_type": "BREAKOUT",
                        "current_state": "ACTIVE",
                        "reason": "Range breakout persisted.",
                        "outcome": {"status": "ACTIVE", "classification": "PENDING"},
                    },
                    {
                        "alert_id": "",
                        "symbol": "AMD",
                        "timestamp": "not-a-time",
                        "alert_type": "VOLUME",
                        "current_state": "WATCH",
                        "reason": "Stored unscorable alert.",
                        "outcome": {
                            "status": "UNSCORABLE_OUTCOME",
                            "classification": "UNSCORABLE_MISSING_ENTRY_PRICE",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
