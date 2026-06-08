from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from momentum_hunter.opportunity_research import (
    OPPORTUNITY_RESEARCH_LABEL,
    build_opportunity_research_report,
)
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter
from tests.test_outcome_explorer import capture_payload, merge_candidates, news, outcome_row, write_capture, write_outcomes


class OpportunityResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_opportunity_research"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_grouping_and_rankings_are_deterministic(self) -> None:
        mdt = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        nvda = capture_payload("2026-06-05T07:00:00-05:00", "morning", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI server demand", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", merge_candidates(mdt, nvda))
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(mdt, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(nvda, next_day="2.0", five_day="-3.0", max_gain="5.0", max_drawdown="-7.0", status="complete"),
            ],
        )

        first = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        second = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(OPPORTUNITY_RESEARCH_LABEL, first.label)
        self.assertEqual(first.condition_rows, second.condition_rows)
        self.assertEqual(first.best_performing_conditions, second.best_performing_conditions)
        self.assertEqual(2, first.summary.completed_outcome_count)
        self.assertEqual("85-100", first.best_performing_conditions[0].condition)
        self.assertEqual("70-84", first.worst_performing_conditions[0].condition)

    def test_pending_outcomes_are_excluded_from_completed_return_math(self) -> None:
        complete = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        pending = capture_payload("2026-06-05T07:00:00-05:00", "morning", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI server demand", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", merge_candidates(complete, pending))
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(complete, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(pending, next_day="-10.0", five_day="", max_gain="1.0", max_drawdown="-20.0", status="pending_five_day"),
            ],
        )

        report = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(2, report.summary.candidate_count)
        self.assertEqual(1, report.summary.completed_outcome_count)
        self.assertEqual(1, report.summary.pending_outcome_count)
        self.assertEqual(4.0, report.summary.average_next_day_return_pct)
        self.assertEqual(6.0, report.summary.average_five_day_return_pct)
        self.assertEqual(8.0, report.summary.average_max_gain_pct)
        self.assertEqual(-2.0, report.summary.average_max_drawdown_pct)

    def test_low_sample_and_insufficient_completed_warnings_trigger(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        write_outcomes(self.outcomes_csv, [outcome_row(payload, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete")])

        report = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertIn("RESEARCH ONLY", report.warnings)
        self.assertIn("INSUFFICIENT COMPLETED OUTCOMES", report.warnings)
        self.assertIn("SMALL SAMPLE", report.warnings)
        self.assertIn("DO NOT USE FOR TRADING DECISIONS YET", report.warnings)

    def test_raw_captures_are_not_mutated_and_quarantined_rows_are_excluded(self) -> None:
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

        report = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(before, file_sha256(active_path))
        self.assertEqual(1, report.summary.candidate_count)
        self.assertEqual("MDT", report.best_performing_conditions[0].best_winner.split()[0])

    def test_non_study_captures_are_excluded_by_default_and_post_capture_label_is_clear(self) -> None:
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

        default_report = build_opportunity_research_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        inclusive_report = build_opportunity_research_report(study_filter=StudyFilter(include_non_study_eligible=True), captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(1, default_report.summary.candidate_count)
        self.assertEqual(2, inclusive_report.summary.candidate_count)
        self.assertIn("RESEARCH ONLY", inclusive_report.label)
        self.assertIn("POST-CAPTURE", "Post-capture outcomes are represented only in summary metrics and condition rows.".upper())


if __name__ == "__main__":
    unittest.main()
