from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.workstation_research_maturity import (
    ResearchMaturityPaths,
    WorkstationResearchMaturityService,
    build_research_maturity_snapshot,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class WorkstationResearchMaturityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.maturity_path = root / "evidence-analytics-maturity-latest.json"
        self.census_path = root / "evidence-census-latest.json"
        self.paths = ResearchMaturityPaths(
            maturity_path=self.maturity_path,
            census_path=self.census_path,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_available_snapshot_preserves_separate_maturity_and_census_denominators(self) -> None:
        self.write_reports()

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("AVAILABLE", snapshot["state"])
        self.assertEqual(100.0, snapshot["maturityCompletionRatePct"])
        self.assertEqual(50.0, snapshot["censusCompletionRatePct"])
        self.assertEqual(1, snapshot["maturityCompletedAlerts"])
        self.assertEqual(2, snapshot["censusTotalAlerts"])
        self.assertEqual(41, snapshot["captures"])
        self.assertEqual(675, snapshot["candidateRows"])
        self.assertEqual(710, snapshot["minuteBars"])
        self.assertEqual(14, snapshot["evidenceRuns"])
        self.assertEqual("LOCKED", snapshot["strategyOptimizationStatus"])
        self.assertFalse(snapshot["strategyChangeRecommendationsAllowed"])
        self.assertTrue(snapshot["researchOnly"])
        self.assertTrue(snapshot["readOnly"])
        self.assertNotIn(str(Path(self.temporary_directory.name)), snapshot["sourceLabel"])

    def test_stale_snapshot_keeps_evidence_visible_and_names_threshold(self) -> None:
        self.write_reports(generated_at="2026-07-20T12:00:00Z")

        snapshot = self.service(stale_after=timedelta(hours=12)).snapshot(
            observed_at=at("2026-07-23T12:00:00Z")
        )

        self.assertEqual("STALE", snapshot["state"])
        self.assertEqual(41, snapshot["captures"])
        self.assertTrue(
            any("12-hour display threshold" in warning for warning in snapshot["warnings"])
        )

    def test_missing_or_invalid_primary_maturity_report_fails_closed(self) -> None:
        self.census_path.write_text(json.dumps(census_payload()), encoding="utf-8")
        missing = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))
        self.maturity_path.write_text("{invalid", encoding="utf-8")
        invalid = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        for snapshot in (missing, invalid):
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertEqual("LOCKED", snapshot["strategyOptimizationStatus"])
            self.assertFalse(snapshot["strategyChangeRecommendationsAllowed"])
            self.assertEqual(0, snapshot["captures"])
            self.assertIn("No research", snapshot["summary"])

    def test_missing_or_invalid_census_is_partial_without_erasing_maturity(self) -> None:
        self.maturity_path.write_text(json.dumps(maturity_payload()), encoding="utf-8")
        missing = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))
        self.census_path.write_text("{invalid", encoding="utf-8")
        invalid = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        for snapshot in (missing, invalid):
            self.assertEqual("PARTIAL", snapshot["state"])
            self.assertEqual(1, snapshot["maturityCompletedAlerts"])
            self.assertEqual(0, snapshot["captures"])
            self.assertEqual("LOCKED", snapshot["strategyOptimizationStatus"])

    def test_rejected_census_does_not_contribute_source_provenance(self) -> None:
        self.maturity_path.write_text(json.dumps(maturity_payload()), encoding="utf-8")
        self.census_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-07-22T00:00:00Z",
                    "engine_version": "wrong",
                }
            ),
            encoding="utf-8",
        )

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("PARTIAL", snapshot["state"])
        self.assertEqual("2026-07-23T11:30:00Z", snapshot["sourceAsOf"])
        self.assertIsNone(snapshot["censusGeneratedAt"])
        self.assertEqual(0, snapshot["captures"])

    def test_strategy_change_unlock_at_top_level_or_gate_fails_closed(self) -> None:
        top_level = maturity_payload()
        top_level["strategy_change_recommendations_allowed"] = True
        self.write_reports(maturity=top_level)
        top_snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        gate = maturity_payload()
        gate["overall_gates"][1]["strategy_change_allowed"] = True
        self.write_reports(maturity=gate)
        gate_snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        for snapshot in (top_snapshot, gate_snapshot):
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertFalse(snapshot["strategyChangeRecommendationsAllowed"])
            self.assertEqual("LOCKED", snapshot["strategyOptimizationStatus"])

    def test_hidden_gate_unlock_and_optimization_status_fail_closed(self) -> None:
        hidden_gate = maturity_payload()
        hidden_gate["overall_gates"] = [
            gate_row(f"Gate {index:02d}", required=index, completed=1)
            for index in range(21)
        ]
        hidden_gate["overall_gates"][20]["strategy_change_allowed"] = True
        self.write_reports(maturity=hidden_gate)
        hidden_snapshot = self.service().snapshot(
            observed_at=at("2026-07-23T12:00:00Z")
        )

        optimization = maturity_payload()
        optimization["strategy_optimization_status"] = "REVIEW"
        optimization["evidence_gate"]["strategy_optimization_status"] = "REVIEW"
        self.write_reports(maturity=optimization)
        optimization_snapshot = self.service().snapshot(
            observed_at=at("2026-07-23T12:00:00Z")
        )

        self.assertEqual("UNAVAILABLE", hidden_snapshot["state"])
        self.assertEqual("UNAVAILABLE", optimization_snapshot["state"])
        self.assertEqual("LOCKED", optimization_snapshot["strategyOptimizationStatus"])

    def test_inconsistent_maturity_or_census_counts_do_not_look_available(self) -> None:
        maturity = maturity_payload()
        maturity["total_alerts"] = 9
        self.write_reports(maturity=maturity)
        bad_maturity = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        census = census_payload()
        census["alerts"]["total_alerts"] = 9
        self.write_reports(census=census)
        bad_census = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("UNAVAILABLE", bad_maturity["state"])
        self.assertEqual("PARTIAL", bad_census["state"])
        self.assertEqual(1, bad_census["maturityCompletedAlerts"])

    def test_inconsistent_gate_evidence_gap_fails_closed(self) -> None:
        maturity = maturity_payload()
        maturity["overall_gates"][1]["completed_needed"] = 23
        self.write_reports(maturity=maturity)

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertTrue(any("inconsistent evidence gap" in item for item in snapshot["warnings"]))

    def test_inconsistent_current_evidence_gate_gap_fails_closed(self) -> None:
        maturity = maturity_payload()
        maturity["evidence_needed_to_next_gate"] = 23
        self.write_reports(maturity=maturity)

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertTrue(
            any("current evidence gate" in item for item in snapshot["warnings"])
        )

    def test_zero_evidence_is_explicitly_empty(self) -> None:
        maturity = maturity_payload(completed=0, pending=0, unscorable=0)
        maturity["overall_gates"] = [
            gate_row("Collect Evidence", required=0, completed=0),
            gate_row("Identify Patterns", required=25, completed=0),
        ]
        maturity["evidence_gate"]["completed_alerts"] = 0
        maturity["evidence_needed_to_next_gate"] = 25
        census = census_payload(
            completed=0,
            pending=0,
            unscorable=0,
            captures=0,
            candidates=0,
            minute_bars=0,
            evidence_runs=0,
        )
        self.write_reports(maturity=maturity, census=census)

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("EMPTY", snapshot["state"])
        self.assertEqual(0, snapshot["maturityTotalAlerts"])
        self.assertEqual(0, snapshot["captures"])
        self.assertEqual("LOCKED", snapshot["strategyOptimizationStatus"])

    def test_display_rows_are_bounded_while_full_counts_are_preserved(self) -> None:
        maturity = maturity_payload()
        maturity["overall_gates"] = [
            gate_row(f"Gate {index:02d}", required=index, completed=1)
            for index in range(25)
        ]
        maturity["can_answer"] = {
            f"question_{index:02d}": f"answer {index}"
            for index in range(25)
        }
        census = census_payload()
        census["table_counts"] = {f"table_{index:02d}": index for index in range(60)}
        self.write_reports(maturity=maturity, census=census)

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual(25, snapshot["gateCount"])
        self.assertEqual(20, snapshot["displayedGateCount"])
        self.assertEqual(25, snapshot["questionCount"])
        self.assertEqual(20, snapshot["displayedQuestionCount"])
        self.assertEqual(60, snapshot["tableCount"])
        self.assertEqual(50, snapshot["displayedTableCount"])

    def test_service_cache_returns_defensive_copies_and_invalidates_on_source_change(self) -> None:
        self.write_reports()
        service = self.service()

        first = service.snapshot(observed_at=at("2026-07-23T12:00:00Z"))
        first["warnings"].append("caller mutation")
        second = service.snapshot(observed_at=at("2026-07-23T12:00:00Z"))
        self.assertNotIn("caller mutation", second["warnings"])

        census = census_payload(captures=42)
        self.census_path.write_text(json.dumps(census), encoding="utf-8")
        next_second = self.census_path.stat().st_mtime_ns + 1_000_000_000
        os.utime(self.census_path, ns=(next_second, next_second))
        refreshed = service.snapshot(observed_at=at("2026-07-23T12:00:00Z"))
        self.assertEqual(42, refreshed["captures"])

    def test_snapshot_reads_never_mutate_persisted_sources(self) -> None:
        self.write_reports()
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.maturity_path, self.census_path)
        }

        self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.maturity_path, self.census_path)
        }
        self.assertEqual(before, after)

    def test_loader_rejects_wrong_schema_and_engine_versions(self) -> None:
        maturity = maturity_payload()
        maturity["schema_version"] = 2
        census = census_payload()
        census["engine_version"] = "some_other_engine"
        self.write_reports(maturity=maturity, census=census)

        snapshot = self.service().snapshot(observed_at=at("2026-07-23T12:00:00Z"))

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertTrue(any("unsupported schema" in item for item in snapshot["warnings"]))

    def test_projection_does_not_import_maturity_builders_database_or_production_logic(self) -> None:
        source_path = Path("momentum_hunter") / "workstation_research_maturity.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )

        forbidden = {
            "sqlite3",
            "momentum_hunter.evidence_analytics_maturity",
            "momentum_hunter.evidence_census",
            "momentum_hunter.outcome_maturity",
            "momentum_hunter.scoring",
            "momentum_hunter.alerts",
            "momentum_hunter.trade_planning",
            "momentum_hunter.execution",
        }
        self.assertTrue(forbidden.isdisjoint(imported), sorted(imported & forbidden))

    def test_nonpositive_stale_threshold_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WorkstationResearchMaturityService(
                self.paths,
                stale_after=timedelta(0),
            )
        with self.assertRaises(ValueError):
            build_research_maturity_snapshot(
                maturity_payload=maturity_payload(),
                census_payload=census_payload(),
                paths=self.paths,
                observed_at=at("2026-07-23T12:00:00Z"),
                stale_after=timedelta(seconds=-1),
            )

    def service(
        self,
        *,
        stale_after: timedelta = timedelta(hours=24),
    ) -> WorkstationResearchMaturityService:
        return WorkstationResearchMaturityService(
            self.paths,
            stale_after=stale_after,
        )

    def write_reports(
        self,
        *,
        maturity: dict | None = None,
        census: dict | None = None,
        generated_at: str | None = None,
    ) -> None:
        maturity = maturity or maturity_payload()
        census = census or census_payload()
        if generated_at is not None:
            maturity["generated_at"] = generated_at
            census["generated_at"] = generated_at
        self.maturity_path.write_text(json.dumps(maturity), encoding="utf-8")
        self.census_path.write_text(json.dumps(census), encoding="utf-8")


def maturity_payload(
    *,
    completed: int = 1,
    pending: int = 0,
    unscorable: int = 1,
) -> dict:
    total = completed + pending + unscorable
    return {
        "schema_version": 1,
        "engine_version": "evidence_analytics_maturity_v1",
        "generated_at": "2026-07-23T11:30:00Z",
        "overall_status": "WARN",
        "total_alerts": total,
        "completed_alerts": completed,
        "pending_alerts": pending,
        "unscorable_alerts": unscorable,
        "completion_rate_pct": 100.0 if completed else 0.0,
        "measurable_edge_status": "INSUFFICIENT_SAMPLE",
        "evidence_gate": {
            "completed_alerts": completed,
            "required_alerts": 25,
            "evidence_status": "COLLECTING",
            "allowed_action": "Collect evidence only",
            "strategy_optimization_status": "LOCKED",
            "reason": f"{completed} completed alert(s); minimum 25 required.",
        },
        "overall_gates": [
            gate_row("Collect Evidence", required=0, completed=completed),
            gate_row("Identify Patterns", required=25, completed=completed),
            gate_row("Recommend Investigations", required=50, completed=completed),
            gate_row("Strategy Modification Review", required=100, completed=completed),
        ],
        "evidence_needed_to_next_gate": max(0, 25 - completed),
        "strategy_optimization_status": "LOCKED",
        "strategy_change_recommendations_allowed": False,
        "sample_confidence": "COLLECTING_ONLY",
        "can_answer": {
            "are_alerts_predictive": "NOT_YET",
            "does_system_have_edge": "NOT_YET",
        },
        "warnings": ["INSUFFICIENT_COMPLETED_ALERTS_FOR_PATTERN_REVIEW"],
        "safety_notes": [
            "Report-only analysis; no scoring, readiness, alert, or trade-planning logic changed.",
            "Strategy changes remain locked.",
        ],
    }


def gate_row(name: str, *, required: int, completed: int) -> dict:
    return {
        "name": name,
        "required_completed_alerts": required,
        "allowed_action": "Collect evidence only",
        "strategy_change_allowed": False,
        "status": "UNLOCKED" if completed >= required else "LOCKED",
        "current_completed_alerts": completed,
        "completed_needed": max(0, required - completed),
    }


def census_payload(
    *,
    completed: int = 1,
    pending: int = 0,
    unscorable: int = 1,
    captures: int = 41,
    candidates: int = 675,
    minute_bars: int = 710,
    evidence_runs: int = 14,
) -> dict:
    total = completed + pending + unscorable
    return {
        "schema_version": 1,
        "engine_version": "sqlite_evidence_census_v1",
        "generated_at": "2026-07-23T11:35:00Z",
        "overall_status": "WARN",
        "table_counts": {
            "opportunity_alerts": total,
            "captures": captures,
            "capture_candidates": candidates,
            "minute_bars": minute_bars,
            "evidence_runs": evidence_runs,
        },
        "alerts": {
            "total_alerts": total,
            "completed": completed,
            "pending": pending,
            "unscorable": unscorable,
            "completion_rate_pct": (completed / total * 100.0) if total else 0.0,
        },
        "captures": {
            "total_captures": captures,
            "total_candidates": candidates,
            "study_eligible": max(0, captures - 5),
            "quarantined": 0,
        },
        "minute_bars": {
            "total_bars": minute_bars,
            "symbols": 1 if minute_bars else 0,
        },
        "evidence_runs": {
            "runs": evidence_runs,
            "metrics": evidence_runs * 10,
        },
        "user_state": {
            "candidate_reviews": 17,
            "watchlist_items": 8,
            "entry_plans": 27,
            "complete_entry_plans": 0,
            "incomplete_entry_plans": 27,
        },
        "warnings": ["LOW_COMPLETED_ALERT_SAMPLE"],
    }


if __name__ == "__main__":
    unittest.main()
