from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from momentum_hunter.candidate_story_view_model import (
    build_candidate_story_summary,
    format_candidate_story_header_html,
    format_story_marker_detail,
    format_story_percent,
    percent_change,
    story_marker_specs,
)
from momentum_hunter.replay import build_candidate_timeline
from momentum_hunter.score_breakdowns import SCORE_ENGINE_VERSION, build_score_breakdown_for_raw_candidate
from tests.test_replay import capture_payload, write_capture


class CandidateStoryViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_candidate_story_view_model"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.score_path = self.root / "score-breakdowns.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_empty_story_summary_is_honest(self) -> None:
        summary = build_candidate_story_summary([])

        self.assertEqual("Insufficient data", summary.status)
        self.assertEqual(0, summary.trusted_capture_count)
        self.assertIn("No trusted captures", summary.warnings[0])

    def test_story_summary_preserves_capture_time_facts(self) -> None:
        rows = self._timeline_rows()
        summary = build_candidate_story_summary(rows)

        self.assertEqual("COO", summary.ticker)
        self.assertEqual("Cool Corp", summary.company)
        self.assertEqual(3, summary.trusted_capture_count)
        self.assertEqual(82.0, summary.first_price)
        self.assertEqual(86.0, summary.latest_price)
        self.assertEqual(94, summary.peak_score)
        self.assertEqual("Peak score", summary.points[1].note)
        self.assertIn("Latest capture", summary.points[2].note)
        self.assertEqual([("First seen", 0), ("Peak score", 1), ("Latest capture", 2)], story_marker_specs(summary))
        self.assertIn("score 94", format_story_marker_detail(summary, "Peak score", 1))

    def test_header_html_uses_readable_story_labels(self) -> None:
        summary = build_candidate_story_summary(self._timeline_rows())
        html = format_candidate_story_header_html(summary)

        self.assertIn("First seen", html)
        self.assertIn("Move since first seen", html)
        self.assertIn("Trusted captures", html)
        self.assertIn("Cool Corp", html)

    def test_percent_formatting_and_math(self) -> None:
        self.assertEqual(25.0, percent_change(100.0, 125.0))
        self.assertIsNone(percent_change(0.0, 125.0))
        self.assertEqual("+3.2%", format_story_percent(3.234))
        self.assertEqual("-1.5%", format_story_percent(-1.5))
        self.assertEqual("n/a", format_story_percent(None))

    def _timeline_rows(self):
        first = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Basic Momentum", price=82.0, score=90)
        second = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Basic Momentum", price=84.5, score=94)
        third = capture_payload("2026-06-08T07:00:00-05:00", "morning", "Basic Momentum", price=86.0, score=91)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", first)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", second)
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", third)
        self._write_score_store([first, second, third])
        return build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.root / "integrity" / "capture_manifest.json",
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.root / "review-decisions.json",
            outcomes_csv=self.root / "analysis-outcomes.csv",
        )

    def _write_score_store(self, captures: list[dict]) -> None:
        records = {}
        for capture in captures:
            record = build_score_breakdown_for_raw_candidate(capture, capture["candidates"][0])
            records[record["identity_key"]] = record
        self.score_path.write_text(
            json.dumps({"schema_version": 1, "score_engine_version": SCORE_ENGINE_VERSION, "records": records}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
