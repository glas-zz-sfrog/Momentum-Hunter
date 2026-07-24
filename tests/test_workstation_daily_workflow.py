from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.entry_plans import upsert_entry_plan
from momentum_hunter.operator_review import OperatorReviewState
from momentum_hunter.outcome_maturity import OutcomeMaturityReport, ReadinessGate
from momentum_hunter.review import CandidateIdentity, ReviewStatus, make_capture_id, upsert_review_decision
from momentum_hunter.workstation_daily_workflow import (
    WorkstationDailyWorkflowPaths,
    build_daily_workflow_snapshot,
)


class WorkstationDailyWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.paths = WorkstationDailyWorkflowPaths.from_data_dir(self.data_dir)
        self.observed_at = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)
        self.capture_time = self.observed_at - timedelta(minutes=10)
        self.write_capture("live", self.capture_time)
        self.write_capture("morning", self.observed_at.replace(hour=12))
        self.write_capture("evening", self.observed_at - timedelta(hours=12))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_snapshot_matches_exact_review_and_plan_identity(self) -> None:
        self.write_report(["AAA", "BBB"], generated_at=self.observed_at - timedelta(minutes=5))
        aaa = self.identity("AAA")
        bbb = self.identity("BBB")
        decisions = {}
        upsert_review_decision(
            decisions,
            aaa,
            ReviewStatus.WATCHLIST,
            decision_timestamp=self.observed_at,
            path=self.paths.review_decisions_path,
        )
        upsert_review_decision(
            decisions,
            bbb,
            ReviewStatus.REJECTED,
            decision_timestamp=self.observed_at,
            path=self.paths.review_decisions_path,
        )
        upsert_entry_plan(
            {},
            aaa,
            trigger="Break 10",
            stop="9",
            invalidation="Lose support",
            max_loss="$25",
            path=self.paths.entry_plans_path,
        )

        with patch(
            "momentum_hunter.workstation_daily_workflow.build_outcome_maturity_report",
            return_value=self.maturity(),
        ):
            snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("AVAILABLE", snapshot["state"])
        self.assertEqual(100, snapshot["workflowScore"])
        self.assertEqual(
            {"total": 2, "reviewed": 2, "unreviewed": 0, "interested": 0, "rejected": 1, "watchlist": 1},
            snapshot["review"],
        )
        self.assertEqual(1, snapshot["plans"]["complete"])
        self.assertEqual(0, snapshot["plans"]["incomplete"])
        self.assertEqual("CURRENT_MANUAL_SCAN", snapshot["operatorContextState"])
        self.assertEqual("Next Required Action: generate the Watchlist Report", snapshot["nextAction"]["title"])
        self.assertEqual(
            ["capture", "review", "plans", "report", "readiness"],
            [step["id"] for step in snapshot["steps"]],
        )
        self.assertEqual("active", snapshot["steps"][3]["level"])
        self.assertTrue(snapshot["readOnly"])

    def test_stale_historical_snapshot_is_visible_but_blocked(self) -> None:
        generated_at = self.observed_at - timedelta(hours=25)
        self.write_report(["AAA"], generated_at=generated_at, session="morning")
        self.paths.review_decisions_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.review_decisions_path.write_text('{"schema_version": 1, "decisions": {}}', encoding="utf-8")
        self.paths.entry_plans_path.write_text('{"schema_version": 1, "plans": {}}', encoding="utf-8")
        self.write_capture("morning", self.capture_time, candidate_symbols=["AAA"])

        with patch(
            "momentum_hunter.workstation_daily_workflow.build_outcome_maturity_report",
            return_value=self.maturity(),
        ):
            snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("STALE", snapshot["state"])
        self.assertEqual(OperatorReviewState.HISTORICAL_READ_ONLY.value, snapshot["operatorContextState"])
        self.assertEqual("blocked", snapshot["nextAction"]["level"])
        self.assertIn("restore a reviewable current workflow", snapshot["nextAction"]["title"])
        self.assertTrue(any("24-hour evidence window" in warning for warning in snapshot["warnings"]))

    def test_missing_report_is_explicitly_unavailable(self) -> None:
        snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], snapshot["steps"])
        self.assertEqual(0, snapshot["review"]["total"])
        self.assertIn("No persisted trade-planning report", snapshot["summary"])

    def test_invalid_candidate_collection_is_unavailable_not_empty(self) -> None:
        self.paths.reports_dir.mkdir(parents=True)
        path = self.paths.reports_dir / "event-trade-plan-briefing-invalid.json"
        path.write_text(
            json.dumps({"metadata": self.metadata(self.observed_at), "candidates": {"symbol": "AAA"}}),
            encoding="utf-8",
        )

        snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertIn("no valid candidate collection", snapshot["summary"])

    def test_missing_review_and_plan_sources_are_partial(self) -> None:
        self.write_report(["AAA"], generated_at=self.observed_at)

        with patch(
            "momentum_hunter.workstation_daily_workflow.build_outcome_maturity_report",
            return_value=self.maturity(),
        ):
            snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("PARTIAL", snapshot["state"])
        self.assertEqual(1, snapshot["review"]["unreviewed"])
        self.assertEqual(0, snapshot["plans"]["watchlist"])
        self.assertTrue(any("Review decisions are unavailable" in warning for warning in snapshot["warnings"]))
        self.assertTrue(any("Entry-plan evidence is unavailable" in warning for warning in snapshot["warnings"]))

    def test_duplicate_and_malformed_rows_are_excluded_without_inflating_counts(self) -> None:
        self.write_report_rows(
            [{"symbol": "AAA", "company": "Alpha"}, {"symbol": "aaa"}, {"company": "Missing"}, "bad"],
            generated_at=self.observed_at,
        )
        self.paths.review_decisions_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.review_decisions_path.write_text('{"schema_version": 1, "decisions": {}}', encoding="utf-8")
        self.paths.entry_plans_path.write_text('{"schema_version": 1, "plans": {}}', encoding="utf-8")

        with patch(
            "momentum_hunter.workstation_daily_workflow.build_outcome_maturity_report",
            return_value=self.maturity(),
        ):
            snapshot = build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual("PARTIAL", snapshot["state"])
        self.assertEqual(1, snapshot["review"]["total"])
        self.assertTrue(any("3 malformed or duplicate" in warning for warning in snapshot["warnings"]))

    def test_projection_does_not_mutate_any_source_file(self) -> None:
        report_path = self.write_report(["AAA"], generated_at=self.observed_at)
        identity = self.identity("AAA")
        upsert_review_decision(
            {},
            identity,
            ReviewStatus.REJECTED,
            decision_timestamp=self.observed_at,
            path=self.paths.review_decisions_path,
        )
        self.paths.entry_plans_path.write_text('{"schema_version": 1, "plans": {}}', encoding="utf-8")
        source_paths = [
            report_path,
            self.paths.review_decisions_path,
            self.paths.entry_plans_path,
            self.paths.captures_dir / "2026-07-23" / "live.json",
            self.paths.captures_dir / "2026-07-23" / "morning.json",
            self.paths.captures_dir / "2026-07-23" / "evening.json",
        ]
        before = {path: self.hash(path) for path in source_paths}

        with patch(
            "momentum_hunter.workstation_daily_workflow.build_outcome_maturity_report",
            return_value=self.maturity(),
        ):
            build_daily_workflow_snapshot(paths=self.paths, observed_at=self.observed_at)

        self.assertEqual(before, {path: self.hash(path) for path in source_paths})

    def write_report(
        self,
        symbols: list[str],
        *,
        generated_at: datetime,
        session: str = "live",
    ) -> Path:
        return self.write_report_rows(
            [{"symbol": symbol, "company": f"{symbol} Company"} for symbol in symbols],
            generated_at=generated_at,
            session=session,
        )

    def write_report_rows(
        self,
        rows: list[object],
        *,
        generated_at: datetime,
        session: str = "live",
    ) -> Path:
        self.paths.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.paths.reports_dir / "event-trade-plan-briefing-2026-07-23-live.json"
        path.write_text(
            json.dumps({"metadata": self.metadata(generated_at, session=session), "candidates": rows}),
            encoding="utf-8",
        )
        return path

    def metadata(self, generated_at: datetime, *, session: str = "live") -> dict[str, str]:
        return {
            "generated_at": generated_at.isoformat(),
            "source_capture_time": self.capture_time.isoformat(),
            "source_session": session,
            "source_provider": "finviz",
            "source_scanner": "Base Momentum",
        }

    def write_capture(
        self,
        session: str,
        capture_time: datetime,
        *,
        candidate_symbols: list[str] | None = None,
    ) -> Path:
        path = self.paths.captures_dir / capture_time.astimezone(timezone.utc).date().isoformat() / f"{session}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "capture_time": capture_time.isoformat(),
                    "capture_date": capture_time.date().isoformat(),
                    "session": session,
                    "provider": "finviz",
                    "scanner": {"name": "Base Momentum"},
                    "next_market_session_date": "2026-07-24",
                    "candidates": [{"ticker": symbol} for symbol in (candidate_symbols or ["AAA"])],
                }
            ),
            encoding="utf-8",
        )
        return path

    def identity(self, symbol: str) -> CandidateIdentity:
        capture_date = self.capture_time.astimezone(timezone.utc).date().isoformat()
        return CandidateIdentity(
            capture_id=make_capture_id(capture_date, "live", "finviz", "Base Momentum"),
            capture_date=capture_date,
            session="live",
            provider="finviz",
            scanner="Base Momentum",
            ticker=symbol,
        )

    @staticmethod
    def maturity() -> OutcomeMaturityReport:
        gates = [
            ReadinessGate("Outcome Explorer", "READY", 25, 20, "Ready", "ready"),
            ReadinessGate("Opportunity Research", "READY", 55, 50, "Ready", "ready"),
        ]
        return OutcomeMaturityReport(
            label="test",
            source="test",
            filters=None,
            total_candidates=60,
            study_eligible_candidates=60,
            completed_next_day_outcomes=25,
            completed_five_day_outcomes=55,
            pending_next_day_outcomes=35,
            pending_five_day_outcomes=5,
            completed_outcome_pct=91.7,
            pending_outcome_pct=8.3,
            earliest_capture_date="2026-06-01",
            latest_capture_date="2026-07-23",
            earliest_date_with_usable_five_day_outcomes="2026-06-01",
            latest_date_with_pending_five_day_outcomes="2026-07-23",
            gates=gates,
            warnings=[],
        )

    @staticmethod
    def hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
