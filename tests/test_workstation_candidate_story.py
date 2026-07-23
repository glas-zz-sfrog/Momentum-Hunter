from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from momentum_hunter.replay import build_candidate_timeline
from momentum_hunter.time_utils import CENTRAL_TZ
from momentum_hunter.workstation_candidate_story import (
    CandidateStoryWorkspaceService,
    build_candidate_story_snapshot,
    normalize_candidate_story_symbol,
)
from tests.test_replay import capture_payload, write_capture, write_score_store


class WorkstationCandidateStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_workstation_candidate_story"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_path = self.root / "analysis-outcomes.csv"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.now = datetime(2026, 7, 23, 12, 0, tzinfo=CENTRAL_TZ)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_snapshot_projects_canonical_story_without_reclassifying_it(self) -> None:
        first = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        peak = capture_payload(
            "2026-06-18T19:00:00-05:00",
            "evening",
            "Base Momentum",
            price=112.0,
            score=96,
        )
        latest = capture_payload(
            "2026-06-22T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=110.0,
            score=89,
        )
        self._write_captures([first, peak, latest])
        write_score_store(self.score_path, [first, peak, latest])

        snapshot = self._service().snapshot("coo")

        self.assertEqual(1, snapshot["schemaVersion"])
        self.assertEqual("COO", snapshot["symbol"])
        self.assertEqual("PARTIAL", snapshot["state"])
        self.assertEqual("Holding", snapshot["status"])
        self.assertEqual(3, snapshot["trustedCaptureCount"])
        self.assertEqual(3, snapshot["totalPointCount"])
        self.assertEqual(3, snapshot["displayedPointCount"])
        self.assertEqual([1, 2, 3], [point["sequence"] for point in snapshot["points"]])
        self.assertEqual([80.0, 96.0, 89.0], [point["score"] for point in snapshot["points"]])
        self.assertEqual("Peak score", snapshot["points"][1]["captureNote"])
        self.assertIn("Latest capture", snapshot["points"][2]["captureNote"])
        self.assertEqual("raw capture", snapshot["points"][0]["captureFactSource"])
        self.assertEqual("later review/outcome annotation", snapshot["points"][0]["laterAnnotationSource"])
        self.assertTrue(all(point["trusted"] for point in snapshot["points"]))
        self.assertTrue(snapshot["readOnly"])
        self.assertIn("no score, readiness, plan, or execution state was changed", snapshot["summary"])

    def test_empty_and_single_capture_states_are_honest(self) -> None:
        empty = self._service().snapshot("NONE")
        self.assertEqual("EMPTY", empty["state"])
        self.assertEqual("Insufficient data", empty["status"])
        self.assertEqual([], empty["points"])

        only = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        self._write_captures([only])
        write_score_store(self.score_path, [only])
        partial = self._service().snapshot("COO")
        self.assertEqual("PARTIAL", partial["state"])
        self.assertEqual("Insufficient data", partial["status"])
        self.assertTrue(
            any("Only one capture is available" in warning for warning in partial["warnings"])
        )

    def test_default_projection_excludes_ordinary_non_trading_day_capture(self) -> None:
        weekday = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        weekend = capture_payload(
            "2026-06-20T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=105.0,
            score=88,
        )
        self._write_captures([weekday, weekend])
        write_score_store(self.score_path, [weekday, weekend])

        snapshot = self._service().snapshot("COO")

        self.assertEqual(1, snapshot["trustedCaptureCount"])
        self.assertEqual("2026-06-17T07:00:00-05:00", snapshot["points"][0]["capturedAt"])

    def test_bounded_display_keeps_full_counts_and_latest_chronology(self) -> None:
        captures = [
            capture_payload(
                timestamp,
                session,
                "Base Momentum",
                price=100.0 + index,
                score=80 + index,
            )
            for index, (timestamp, session) in enumerate(
                [
                    ("2026-06-17T07:00:00-05:00", "morning"),
                    ("2026-06-17T19:00:00-05:00", "evening"),
                    ("2026-06-18T07:00:00-05:00", "morning"),
                    ("2026-06-18T19:00:00-05:00", "evening"),
                ]
            )
        ]
        self._write_captures(captures)
        write_score_store(self.score_path, captures)
        rows = self._timeline()

        snapshot = build_candidate_story_snapshot(
            "COO",
            list(reversed(rows)),
            observed_at=self.now,
            max_display_points=2,
        )

        self.assertEqual(4, snapshot["totalPointCount"])
        self.assertEqual(2, snapshot["displayedPointCount"])
        self.assertEqual([1, 2], [point["sequence"] for point in snapshot["points"]])
        self.assertEqual(
            ["2026-06-18T07:00:00-05:00", "2026-06-18T19:00:00-05:00"],
            [point["capturedAt"] for point in snapshot["points"]],
        )
        self.assertTrue(
            any("Showing the latest 2 of 4" in warning for warning in snapshot["warnings"])
        )

    def test_missing_capture_time_sorts_safely_before_timestamped_rows(self) -> None:
        capture = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        self._write_captures([capture])
        write_score_store(self.score_path, [capture])
        timestamped = self._timeline()[0]
        missing_time = replace(
            timestamped,
            identity_key="missing-capture-time",
            capture_id="missing-capture-time",
            capture_time=None,
            capture_time_text="",
        )

        snapshot = build_candidate_story_snapshot(
            "COO",
            [timestamped, missing_time],
            observed_at=self.now,
        )

        self.assertIsNone(snapshot["points"][0]["capturedAt"])
        self.assertEqual(
            "2026-06-17T07:00:00-05:00",
            snapshot["points"][1]["capturedAt"],
        )

    def test_cache_reuses_unchanged_projection_and_invalidates_on_source_change(self) -> None:
        capture = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        self._write_captures([capture])
        write_score_store(self.score_path, [capture])
        rows = self._timeline()
        calls: list[str] = []

        def timeline_builder(symbol: str, **_: object):
            calls.append(symbol)
            return rows

        service = CandidateStoryWorkspaceService(
            data_dir=self.root,
            timeline_builder=timeline_builder,
            now_provider=lambda: self.now,
        )
        first = service.snapshot("COO")
        first["summary"] = "caller mutation"
        second = service.snapshot("COO")
        self.assertEqual(["COO"], calls)
        self.assertNotEqual("caller mutation", second["summary"])

        capture_path = next(self.captures_dir.rglob("*.json"))
        capture_path.write_text(capture_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        service.snapshot("COO")
        self.assertEqual(["COO", "COO"], calls)

    def test_snapshot_does_not_mutate_any_source_file(self) -> None:
        capture = capture_payload(
            "2026-06-17T07:00:00-05:00",
            "morning",
            "Base Momentum",
            price=100.0,
            score=80,
        )
        self._write_captures([capture])
        write_score_store(self.score_path, [capture])
        before = self._source_hashes()

        self._service().snapshot("COO")

        self.assertEqual(before, self._source_hashes())

    def test_symbol_validation_rejects_path_and_whitespace_inputs(self) -> None:
        self.assertEqual("BRK.B", normalize_candidate_story_symbol(" brk.b "))
        for invalid in ("", "../COO", "COO/TEST", "COO TEST", "A" * 16):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_candidate_story_symbol(invalid)

    def _service(self) -> CandidateStoryWorkspaceService:
        return CandidateStoryWorkspaceService(
            data_dir=self.root,
            now_provider=lambda: self.now,
        )

    def _timeline(self):
        return build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_path,
        )

    def _write_captures(self, captures: list[dict]) -> None:
        for capture in captures:
            scanner = capture["scanner"]["name"].replace(" ", "-").lower()
            path = (
                self.captures_dir
                / capture["capture_date"]
                / f"{capture['session']}-{scanner}-{capture['capture_time'][11:19].replace(':', '')}.json"
            )
            write_capture(path, capture)

    def _source_hashes(self) -> dict[str, str]:
        return {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
