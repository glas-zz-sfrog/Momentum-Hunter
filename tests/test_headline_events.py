from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from momentum_hunter.headline_events import build_headline_dedup_report, fingerprint_headline
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter


class HeadlineEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_headline_events"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_fingerprinting_is_deterministic_and_removes_boilerplate(self) -> None:
        first = fingerprint_headline("MDT: Medtronic Stock Jumps on Strong Earnings - Yahoo Finance", ticker="MDT", source="Yahoo Finance")
        second = fingerprint_headline("Medtronic stock jumps on strong earnings", ticker="MDT")

        self.assertEqual(first, second)
        self.assertEqual(first, fingerprint_headline("MDT: Medtronic Stock Jumps on Strong Earnings - Yahoo Finance", ticker="MDT", source="Yahoo Finance"))

    def test_duplicate_grouping_is_deterministic_and_does_not_inflate_event_count(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [
                news("MDT: Medtronic beats earnings - Yahoo Finance", "2026-06-05T06:30:00-05:00", source="Yahoo Finance"),
                news("Medtronic beats earnings", "2026-06-05T06:31:00-05:00", source="Reuters"),
                news("Medtronic raises guidance", "2026-06-05T06:32:00-05:00", source="Reuters"),
            ],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        first = build_headline_dedup_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        second = build_headline_dedup_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        metrics = [(event.event_id, event.duplicate_headline_count, event.unique_source_count) for event in first.events]

        self.assertEqual(metrics, [(event.event_id, event.duplicate_headline_count, event.unique_source_count) for event in second.events])
        self.assertEqual(2, first.total_events)
        self.assertEqual(3, first.total_raw_headlines)
        duplicated = [event for event in first.events if event.duplicate_headline_count == 2][0]
        self.assertEqual(2, duplicated.unique_source_count)
        self.assertEqual(["MDT"], duplicated.tickers)

    def test_raw_captures_are_not_mutated_and_quarantine_is_excluded(self) -> None:
        active_path = self.captures_dir / "2026-06-05" / "morning.json"
        write_capture(active_path, capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", [news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00")]))
        write_capture(self.quarantine_dir / "bad.json", capture_payload("2026-06-05T07:00:00-05:00", "morning", "BAD", [news("Bad beats earnings", "2026-06-05T06:30:00-05:00")]))
        before = file_sha256(active_path)

        report = build_headline_dedup_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(before, file_sha256(active_path))
        self.assertEqual(["MDT"], sorted({ticker for event in report.events for ticker in event.tickers}))

    def test_non_study_rows_are_excluded_by_default_and_preopen_can_be_included(self) -> None:
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", capture_payload("2026-06-08T07:00:00-05:00", "morning", "MDT", [news("Medtronic beats earnings", "2026-06-08T06:30:00-05:00")]))
        write_capture(self.captures_dir / "2026-06-07" / "preopen.json", capture_payload("2026-06-07T19:00:00-05:00", "preopen", "NVDA", [news("Nvidia AI server demand", "2026-06-07T18:00:00-05:00")]))

        default_report = build_headline_dedup_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        inclusive_report = build_headline_dedup_report(study_filter=StudyFilter(include_non_study_eligible=True), captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(["MDT"], sorted({ticker for event in default_report.events for ticker in event.tickers}))
        self.assertEqual(["MDT", "NVDA"], sorted({ticker for event in inclusive_report.events for ticker in event.tickers}))

    def test_future_and_unknown_timestamps_are_warned_not_treated_as_fresh(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [
                news("Future earnings beat", "2026-06-05T08:30:00-05:00"),
                news("Unknown earnings beat", ""),
            ],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_headline_dedup_report(captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        status_counts = {status: count for event in report.events for status, count in event.timestamp_status_summary.items()}

        self.assertEqual(1, status_counts["future"])
        self.assertEqual(1, status_counts["unknown"])
        self.assertTrue(any("Future timestamp" in warning for warning in report.warnings))
        self.assertTrue(any("FUTURE TIMESTAMP SOURCE ISSUE" in event.warnings for event in report.events))
        self.assertTrue(any("UNKNOWN TIMESTAMP SOURCE ISSUE" in event.warnings for event in report.events))

    def test_source_reliability_and_filters_are_deterministic(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [
                news("Medtronic beats earnings", "2026-06-05T06:30:00-05:00", source="Provider A"),
                news("MDT Medtronic beats earnings", "2026-06-05T06:31:00-05:00", source="Provider A"),
                news("Medtronic beats earnings", "", source="Provider B"),
            ],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_headline_dedup_report(study_filter=StudyFilter(source="Provider A", minimum_duplicate_count=2), captures_dir=self.captures_dir, score_breakdowns_path=self.score_path, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        provider_a = next(row for row in report.source_reliability if row.source == "source:Provider A")

        self.assertEqual(1, report.total_events)
        self.assertEqual(2, report.total_raw_headlines)
        self.assertEqual(100.0, provider_a.exact_pct)
        self.assertEqual(100.0, provider_a.duplicate_rate_pct)
        self.assertEqual(1, provider_a.unique_event_count)


def capture_payload(capture_time: str, session: str, ticker: str, headlines: list[dict]) -> dict:
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
                "sector": "Healthcare",
                "industry": "Medical Devices",
                "score": 96,
                "score_profile": "regime-aware-v1",
                "score_regime": "bull",
                "news": headlines,
            }
        ],
    }


def news(headline: str, published_at: str, *, source: str = "Fixture") -> dict:
    return {
        "headline": headline,
        "source": source,
        "published_at": published_at,
        "url": f"https://example.test/{headline.lower().replace(' ', '-')}",
    }


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
