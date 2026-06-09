from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from momentum_hunter.outcome_maturity import (
    GATE_DIAGNOSTIC,
    GATE_LOCKED,
    GATE_READY,
    ReadinessThresholds,
    build_outcome_maturity_report,
)
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter
from tests.test_outcome_explorer import capture_payload, merge_candidates, news, outcome_row, write_capture, write_outcomes


class OutcomeMaturityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_outcome_maturity"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.analysis_csv = self.root / "analysis-captures.csv"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.thresholds = ReadinessThresholds(
            outcome_explorer_next_day=2,
            opportunity_research_five_day=2,
            opportunity_score_design_five_day=3,
            weight_optimization_five_day=4,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_readiness_counts_are_deterministic_and_pending_is_not_completed(self) -> None:
        complete = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        pending_five = capture_payload("2026-06-05T07:00:00-05:00", "morning", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI server demand", "2026-06-05T06:30:00-05:00")])
        pending_next = capture_payload("2026-06-06T07:00:00-05:00", "morning", "ORCL", 88, "Technology", "Software", [news("Oracle AI demand", "2026-06-06T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", merge_candidates(complete, pending_five))
        write_capture(self.captures_dir / "2026-06-06" / "morning.json", pending_next)
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(complete, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(pending_five, next_day="2.0", five_day="", max_gain="5.0", max_drawdown="-1.0", status="pending_five_day"),
                outcome_row(pending_next, next_day="", five_day="", max_gain="", max_drawdown="", status="pending_next_day"),
            ],
        )

        first = self.build_report()
        second = self.build_report()

        self.assertEqual(first, second)
        self.assertEqual(3, first.total_candidates)
        self.assertEqual(2, first.completed_next_day_outcomes)
        self.assertEqual(1, first.completed_five_day_outcomes)
        self.assertEqual(1, first.pending_next_day_outcomes)
        self.assertEqual(2, first.pending_five_day_outcomes)
        self.assertEqual(33.33, first.completed_outcome_pct)
        self.assertEqual(66.67, first.pending_outcome_pct)
        self.assertEqual("2026-06-05", first.earliest_date_with_usable_five_day_outcomes)
        self.assertEqual("2026-06-06", first.latest_date_with_pending_five_day_outcomes)

    def test_gates_lock_unlock_at_thresholds(self) -> None:
        one = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        two = capture_payload("2026-06-06T07:00:00-05:00", "morning", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI demand", "2026-06-06T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", one)
        write_capture(self.captures_dir / "2026-06-06" / "morning.json", two)
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(one, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(two, next_day="2.0", five_day="3.0", max_gain="5.0", max_drawdown="-1.0", status="complete"),
            ],
        )

        report = self.build_report()
        statuses = {gate.name: gate.status for gate in report.gates}

        self.assertEqual(GATE_READY, statuses["Outcome Explorer"])
        self.assertEqual(GATE_READY, statuses["Opportunity Research"])
        self.assertEqual(GATE_DIAGNOSTIC, statuses["Opportunity Score design"])
        self.assertEqual(GATE_DIAGNOSTIC, statuses["Weight optimization"])

    def test_zero_completed_outcomes_lock_and_estimate_gracefully(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        write_outcomes(self.outcomes_csv, [outcome_row(payload, next_day="", five_day="", max_gain="", max_drawdown="", status="pending_next_day")])

        report = self.build_report()

        self.assertTrue(all(gate.status == GATE_LOCKED for gate in report.gates))
        self.assertTrue(all(gate.estimated_earliest_readiness_date == "unknown - no completed outcomes yet" for gate in report.gates))
        self.assertIn("INSUFFICIENT COMPLETED OUTCOMES", report.warnings)
        self.assertIn("DIAGNOSTIC ONLY", report.warnings)
        self.assertIn("DO NOT USE FOR TRADING DECISIONS", report.warnings)

    def test_quarantined_rows_are_excluded_and_raw_capture_is_not_mutated(self) -> None:
        active = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        quarantined = capture_payload("2026-06-06T07:00:00-05:00", "morning", "BAD", 90, "Technology", "Software", [news("Bad beats earnings", "2026-06-06T06:30:00-05:00")])
        active_path = self.captures_dir / "2026-06-05" / "morning.json"
        write_capture(active_path, active)
        write_capture(self.quarantine_dir / "bad.json", quarantined)
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(active, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(quarantined, next_day="40.0", five_day="60.0", max_gain="80.0", max_drawdown="-2.0", status="complete"),
            ],
        )
        before = file_sha256(active_path)

        report = self.build_report()

        self.assertEqual(before, file_sha256(active_path))
        self.assertEqual(1, report.total_candidates)
        self.assertEqual(1, report.completed_five_day_outcomes)

    def test_non_study_captures_are_excluded_by_default_and_can_be_included(self) -> None:
        morning = capture_payload("2026-06-08T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-08T06:30:00-05:00")])
        preopen = capture_payload("2026-06-07T19:00:00-05:00", "preopen", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI server demand", "2026-06-07T18:00:00-05:00")])
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", morning)
        write_capture(self.captures_dir / "2026-06-07" / "preopen.json", preopen)
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(morning, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(preopen, next_day="2.0", five_day="3.0", max_gain="5.0", max_drawdown="-1.0", status="complete"),
            ],
        )

        default_report = self.build_report()
        inclusive_report = self.build_report(study_filter=StudyFilter(include_non_study_eligible=True))

        self.assertEqual(1, default_report.total_candidates)
        self.assertEqual(2, inclusive_report.total_candidates)
        self.assertEqual(1, default_report.study_eligible_candidates)
        self.assertEqual(1, inclusive_report.study_eligible_candidates)

    def build_report(self, study_filter: StudyFilter | None = None):
        return build_outcome_maturity_report(
            study_filter=study_filter,
            thresholds=self.thresholds,
            captures_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
        )


if __name__ == "__main__":
    unittest.main()
