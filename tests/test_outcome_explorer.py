from __future__ import annotations

import csv
import json
import shutil
import unittest
from pathlib import Path

from momentum_hunter.outcome_explorer import OUTCOME_EXPLORER_LABEL, build_outcome_explorer_report
from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter


class OutcomeExplorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_outcome_explorer"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_summary_metrics_are_deterministic_and_pending_is_excluded_from_return_math(self) -> None:
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

        first = build_outcome_explorer_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        second = build_outcome_explorer_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(OUTCOME_EXPLORER_LABEL, first.label)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(2, first.summary.candidate_count)
        self.assertEqual(1, first.summary.completed_outcome_count)
        self.assertEqual(1, first.summary.pending_outcome_count)
        self.assertEqual(4.0, first.summary.average_next_day_return_pct)
        self.assertEqual(6.0, first.summary.average_five_day_return_pct)
        self.assertEqual(8.0, first.summary.average_max_gain_pct)
        self.assertEqual(-2.0, first.summary.average_max_drawdown_pct)
        self.assertEqual(100.0, first.summary.win_rate_pct)

    def test_filters_are_deterministic(self) -> None:
        mdt = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        nvda = capture_payload("2026-06-05T07:00:00-05:00", "morning", "NVDA", 82, "Technology", "Semiconductors", [news("Nvidia AI server demand", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", merge_candidates(mdt, nvda))
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(mdt, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(nvda, next_day="2.0", five_day="3.0", max_gain="5.0", max_drawdown="-1.0", status="complete"),
            ],
        )

        study_filter = StudyFilter(
            start_date="2026-06-05",
            end_date="2026-06-05",
            score_bucket="85-100",
            minimum_score=90,
            regime="bull",
            scanner="Base Momentum",
            sector="Healthcare",
            industry="Medical",
            ticker="MDT",
            catalyst_cluster="Earnings beat",
            minimum_confidence=80,
            minimum_purity=90,
            timestamp_status="EXACT_TIMESTAMP",
            age_bucket="<1h",
        )
        report = build_outcome_explorer_report(study_filter=study_filter, captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(["MDT"], [candidate.ticker for candidate in report.candidates])
        self.assertEqual(["85-100"], [row.group for row in report.score_bucket_performance])

    def test_quarantined_orphan_outcome_rows_are_excluded_by_default(self) -> None:
        active = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        quarantined = capture_payload("2026-06-06T07:00:00-05:00", "morning", "BAD", 90, "Technology", "Software", [news("Bad beats earnings", "2026-06-06T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", active)
        write_capture(self.quarantine_dir / "bad.json", quarantined)
        write_outcomes(
            self.outcomes_csv,
            [
                outcome_row(active, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete"),
                outcome_row(quarantined, next_day="40.0", five_day="60.0", max_gain="80.0", max_drawdown="-2.0", status="complete"),
            ],
        )

        report = build_outcome_explorer_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(["MDT"], [candidate.ticker for candidate in report.candidates])
        self.assertEqual(1, report.summary.candidate_count)

    def test_non_study_rows_are_excluded_by_default_and_preopen_can_be_included(self) -> None:
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

        default_report = build_outcome_explorer_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        inclusive_report = build_outcome_explorer_report(study_filter=StudyFilter(include_non_study_eligible=True), captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(["MDT"], [candidate.ticker for candidate in default_report.candidates])
        self.assertEqual(["MDT", "NVDA"], sorted([candidate.ticker for candidate in inclusive_report.candidates]))

    def test_raw_captures_are_not_mutated_and_post_capture_label_is_explicit(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", 96, "Healthcare", "Medical Devices", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")])
        capture_path = self.captures_dir / "2026-06-05" / "morning.json"
        write_capture(capture_path, payload)
        write_outcomes(self.outcomes_csv, [outcome_row(payload, next_day="4.0", five_day="6.0", max_gain="8.0", max_drawdown="-2.0", status="complete")])
        before = file_sha256(capture_path)

        report = build_outcome_explorer_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(before, file_sha256(capture_path))
        self.assertIn("POST-CAPTURE", report.label)
        self.assertEqual("complete", report.candidates[0].outcome_status)


def capture_payload(capture_time: str, session: str, ticker: str, score: int, sector: str, industry: str, headlines: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "capture_time": capture_time,
        "capture_date": capture_time[:10],
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
                "company": f"{ticker} Corp",
                "price": 82.0,
                "percent_change": 6.5,
                "volume": 35_000_000,
                "relative_volume": 2.2,
                "market_cap": 75_000_000_000,
                "sector": sector,
                "industry": industry,
                "score": score,
                "score_profile": "regime-aware-v1",
                "score_regime": "bull",
                "news": headlines,
            }
        ],
    }


def merge_candidates(first: dict, second: dict) -> dict:
    merged = json.loads(json.dumps(first))
    merged["candidates"].extend(second["candidates"])
    return merged


def news(headline: str, published_at: str, *, source: str = "Fixture") -> dict:
    return {"headline": headline, "source": source, "published_at": published_at, "url": ""}


def outcome_row(capture: dict, *, next_day: str, five_day: str, max_gain: str, max_drawdown: str, status: str) -> dict:
    candidate = capture["candidates"][0]
    row = {field: "" for field in OUTCOME_FIELDNAMES}
    row.update(
        {
            "capture_date": capture["capture_date"],
            "capture_time": capture["capture_time"],
            "session": capture["session"],
            "is_study_eligible": "true" if capture["session"] in {"morning", "evening"} else "false",
            "provider": capture["provider"],
            "scanner": capture["scanner"]["name"],
            "market_regime": "bull",
            "ticker": candidate["ticker"],
            "score": str(candidate["score"]),
            "sector": candidate["sector"],
            "industry": candidate["industry"],
            "next_day_return_pct": next_day,
            "five_day_return_pct": five_day,
            "max_gain_pct": max_gain,
            "max_drawdown_pct": max_drawdown,
            "outcome_status": status,
        }
    )
    return row


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_outcomes(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
