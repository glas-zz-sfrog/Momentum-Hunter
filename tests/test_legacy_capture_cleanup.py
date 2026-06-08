from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.cleanup_legacy_captures import cleanup_legacy_non_study_captures
from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.replay import build_candidate_timeline
from momentum_hunter.scheduling import classify_capture
from momentum_hunter.storage import ANALYSIS_FIELDNAMES, file_sha256
from momentum_hunter.study import StudyFilter, summarize_capture_rows
from momentum_hunter.time_utils import CENTRAL_TZ


class LegacyCaptureCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_legacy_cleanup"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.quarantine_root = self.root / "quarantine" / "raw-captures"
        self.analysis_csv = self.root / "analysis-captures.csv"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"
        self.review_path = self.root / "review-decisions.json"
        self.score_path = self.root / "score-breakdowns.json"
        self.morning = write_capture(
            self.captures_dir / "2026-06-07" / "morning.json",
            capture_time="2026-06-07T07:00:35-05:00",
            session="morning",
            ticker="LEG",
            include_calendar=False,
        )
        self.evening = write_capture(
            self.captures_dir / "2026-06-07" / "evening.json",
            capture_time="2026-06-07T19:00:33-05:00",
            session="evening",
            ticker="LEG",
            include_calendar=False,
        )
        self.preopen = write_capture(
            self.captures_dir / "2026-06-07" / "preopen.json",
            capture_time="2026-06-07T19:00:03-05:00",
            session="preopen",
            ticker="LEG",
            include_calendar=True,
        )
        write_markdown(self.captures_dir / "2026-06-07" / "morning.md")
        write_markdown(self.captures_dir / "2026-06-07" / "evening.md")
        write_markdown(self.captures_dir / "2026-06-07" / "preopen.md")
        write_derived_rows(self.analysis_csv, self.outcomes_csv)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cleanup_quarantines_sunday_morning_evening_and_preserves_preopen(self) -> None:
        preopen_hash = file_sha256(self.captures_dir / "2026-06-07" / "preopen.json")

        result = cleanup_legacy_non_study_captures(
            "2026-06-07",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
            cleaned_at=datetime(2026, 6, 7, 20, 0, 0, tzinfo=CENTRAL_TZ),
        )

        self.assertEqual(["morning", "evening"], result.quarantined_sessions)
        self.assertFalse((self.captures_dir / "2026-06-07" / "morning.json").exists())
        self.assertFalse((self.captures_dir / "2026-06-07" / "evening.json").exists())
        self.assertTrue((self.captures_dir / "2026-06-07" / "preopen.json").exists())
        self.assertEqual(preopen_hash, file_sha256(self.captures_dir / "2026-06-07" / "preopen.json"))
        self.assertEqual(1, result.analysis_rows)
        self.assertEqual(1, result.outcome_rows)
        self.assertTrue((result.backup_dir / "analysis-captures.csv").exists())
        self.assertTrue((result.backup_dir / "analysis-outcomes.csv").exists())

        analysis_rows = list(csv.DictReader(self.analysis_csv.read_text(encoding="utf-8").splitlines()))
        outcome_rows = list(csv.DictReader(self.outcomes_csv.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(["preopen"], [row["session"] for row in analysis_rows])
        self.assertEqual(["preopen"], [row["session"] for row in outcome_rows])

    def test_study_and_replay_exclude_cleaned_sunday_captures_by_default(self) -> None:
        cleanup_legacy_non_study_captures(
            "2026-06-07",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
            cleaned_at=datetime(2026, 6, 7, 20, 0, 0, tzinfo=CENTRAL_TZ),
        )
        analysis_rows = list(csv.DictReader(self.analysis_csv.read_text(encoding="utf-8").splitlines()))

        default_study = summarize_capture_rows(analysis_rows)
        inclusive_study = summarize_capture_rows(analysis_rows, study_filter=StudyFilter(include_non_study_eligible=True))
        default_replay = build_candidate_timeline(
            "LEG",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        inclusive_replay = build_candidate_timeline(
            "LEG",
            include_quarantined=True,
            include_non_trading_day=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(0, default_study.candidate_count)
        self.assertEqual(1, inclusive_study.candidate_count)
        self.assertEqual(["preopen"], [row.session for row in default_replay])
        self.assertEqual(["evening", "morning", "preopen"], sorted(row.session for row in inclusive_replay))
        quarantined = [row for row in inclusive_replay if row.quarantined]
        self.assertEqual(["evening", "morning"], sorted(row.session for row in quarantined))


def write_capture(path: Path, *, capture_time: str, session: str, ticker: str, include_calendar: bool) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "capture_time": capture_time,
        "capture_date": "2026-06-07",
        "session": session,
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "scoring": {"profile": "regime-aware-v1", "regime": "bull"},
        "market": {"regime": "bull", "symbol": "SPY"},
        "candidates": [
            {
                "rank": 1,
                "ticker": ticker,
                "company": "Legacy Corp",
                "price": 10.0,
                "percent_change": 6.0,
                "volume": 2_000_000,
                "relative_volume": 1.5,
                "market_cap": 2_000_000_000,
                "sector": "Technology",
                "industry": "Software",
                "score": 80,
                "score_profile": "regime-aware-v1",
                "score_regime": "bull",
                "news": [],
            }
        ],
    }
    if include_calendar:
        payload.update(classify_capture(capture_time, session, capture_date="2026-06-07").as_fields())
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def write_markdown(path: Path) -> None:
    path.write_text("# Raw capture report\n", encoding="utf-8")


def write_derived_rows(analysis_csv: Path, outcomes_csv: Path) -> None:
    analysis_csv.parent.mkdir(parents=True, exist_ok=True)
    with analysis_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        writer.writeheader()
        for session in ("morning", "evening", "preopen"):
            row = {field: "" for field in ANALYSIS_FIELDNAMES}
            row.update(
                {
                    "capture_date": "2026-06-07",
                    "capture_time": f"2026-06-07T{'07:00:35' if session == 'morning' else '19:00:03' if session == 'preopen' else '19:00:33'}-05:00",
                    "session": session,
                    "provider": "finviz",
                    "scanner": "Base Momentum",
                    "ticker": "LEG",
                    "score": "80",
                    "price": "10.0",
                    "is_study_eligible": "False",
                }
            )
            writer.writerow(row)
    with outcomes_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        for session in ("morning", "evening", "preopen"):
            row = {field: "" for field in OUTCOME_FIELDNAMES}
            row.update(
                {
                    "capture_date": "2026-06-07",
                    "capture_time": f"2026-06-07T{'07:00:35' if session == 'morning' else '19:00:03' if session == 'preopen' else '19:00:33'}-05:00",
                    "session": session,
                    "provider": "finviz",
                    "scanner": "Base Momentum",
                    "ticker": "LEG",
                    "outcome_status": "pending_next_day",
                }
            )
            writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
