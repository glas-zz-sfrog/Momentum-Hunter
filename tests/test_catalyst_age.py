from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from momentum_hunter.catalyst_age import build_catalyst_age_audit_report, evaluate_timestamp
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter


class CatalystAgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_catalyst_age"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_exact_timestamps_calculate_correct_age_and_bucket(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [news("Medtronic earnings beat", "2026-06-05T06:30:00-05:00")],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_catalyst_age_audit_report(
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        record = report.records[0]

        self.assertEqual("EXACT_TIMESTAMP", record.timestamp_status)
        self.assertEqual(0.5, record.age_at_capture_hours)
        self.assertEqual("<1h", record.age_bucket)
        self.assertEqual("exact", record.timestamp_confidence)
        self.assertEqual(1, report.exact_timestamp_count)

    def test_date_only_and_estimated_timestamps_are_partial_context(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [
                news("Date only earnings item", "2026-06-04"),
                news("Estimated earnings item", "2026-06-05T05:00:00-05:00", estimated=True),
            ],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_catalyst_age_audit_report(
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        statuses = {record.headline: record for record in report.records}

        self.assertEqual("DATE_ONLY", statuses["Date only earnings item"].timestamp_status)
        self.assertEqual(31.0, statuses["Date only earnings item"].age_at_capture_hours)
        self.assertEqual("partial", statuses["Date only earnings item"].timestamp_confidence)
        self.assertEqual("ESTIMATED", statuses["Estimated earnings item"].timestamp_status)
        self.assertEqual("estimated", statuses["Estimated earnings item"].timestamp_confidence)

    def test_missing_timestamps_remain_unknown_not_fresh(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", [news("Missing timestamp", "")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_catalyst_age_audit_report(
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        record = report.records[0]

        self.assertEqual("UNKNOWN_TIMESTAMP", record.timestamp_status)
        self.assertIsNone(record.age_at_capture_hours)
        self.assertEqual("unknown", record.age_bucket)
        self.assertEqual("unknown", record.timestamp_confidence)
        self.assertIn("freshness is not inferred", report.warnings[0])

    def test_future_and_invalid_timestamps_are_warned_and_not_fresh(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "MDT",
            [
                news("Future timestamp", "2026-06-05T08:00:00-05:00"),
                news("Invalid timestamp", "not-a-date"),
            ],
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_catalyst_age_audit_report(
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        by_headline = {record.headline: record for record in report.records}

        self.assertEqual("FUTURE_TIMESTAMP", by_headline["Future timestamp"].timestamp_status)
        self.assertEqual("invalid_future", by_headline["Future timestamp"].age_bucket)
        self.assertEqual("invalid", by_headline["Future timestamp"].timestamp_confidence)
        self.assertEqual("INVALID_TIMESTAMP", by_headline["Invalid timestamp"].timestamp_status)
        self.assertEqual("unknown", by_headline["Invalid timestamp"].age_bucket)
        self.assertEqual(1, report.future_timestamp_count)
        self.assertEqual(1, report.invalid_timestamp_count)
        self.assertTrue(any("future timestamp" in warning for warning in report.warnings))

    def test_age_buckets_are_deterministic(self) -> None:
        capture_dt = "2026-06-05T12:00:00-05:00"
        headlines = [
            news("<1", "2026-06-05T11:30:00-05:00"),
            news("1-4", "2026-06-05T10:00:00-05:00"),
            news("4-12", "2026-06-05T06:00:00-05:00"),
            news("12-24", "2026-06-04T18:00:00-05:00"),
            news("1-3d", "2026-06-03T12:00:00-05:00"),
            news("3d+", "2026-06-01T12:00:00-05:00"),
        ]
        payload = capture_payload(capture_dt, "morning", "MDT", headlines)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        first = build_catalyst_age_audit_report(captures_dir=self.captures_dir, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        second = build_catalyst_age_audit_report(captures_dir=self.captures_dir, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(first.age_bucket_distribution, second.age_bucket_distribution)
        self.assertEqual(1, first.age_bucket_distribution["<1h"])
        self.assertEqual(1, first.age_bucket_distribution["1-4h"])
        self.assertEqual(1, first.age_bucket_distribution["4-12h"])
        self.assertEqual(1, first.age_bucket_distribution["12-24h"])
        self.assertEqual(1, first.age_bucket_distribution["1-3d"])
        self.assertEqual(1, first.age_bucket_distribution["3d+"])

    def test_raw_captures_are_not_mutated_and_quarantine_is_excluded_by_default(self) -> None:
        active_path = self.captures_dir / "2026-06-05" / "morning.json"
        quarantined_path = self.root / "quarantine" / "raw-captures" / "batch" / "2026-06-05-evening.json"
        write_capture(active_path, capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", [news("Active earnings beat", "2026-06-05T06:30:00-05:00")]))
        write_capture(quarantined_path, capture_payload("2026-06-05T19:00:00-05:00", "evening", "BAD", [news("Quarantined AI story", "2026-06-05T18:30:00-05:00")]))
        before = file_sha256(active_path)

        report = build_catalyst_age_audit_report(
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(before, file_sha256(active_path))
        self.assertEqual(["MDT"], sorted({record.ticker for record in report.records}))

    def test_non_study_rows_are_excluded_by_default_and_preopen_requires_explicit_include(self) -> None:
        morning = capture_payload("2026-06-08T07:00:00-05:00", "morning", "MDT", [news("Market day earnings beat", "2026-06-08T06:30:00-05:00")])
        preopen = capture_payload("2026-06-07T19:00:00-05:00", "preopen", "OSCR", [news("Preopen FDA update", "2026-06-07T18:00:00-05:00")])
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", morning)
        write_capture(self.captures_dir / "2026-06-07" / "preopen.json", preopen)

        default_report = build_catalyst_age_audit_report(captures_dir=self.captures_dir, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)
        inclusive_report = build_catalyst_age_audit_report(study_filter=StudyFilter(include_non_study_eligible=True), captures_dir=self.captures_dir, review_decisions_path=self.review_path, outcomes_csv=self.outcomes_csv)

        self.assertEqual(["MDT"], sorted({record.ticker for record in default_report.records}))
        self.assertEqual(["MDT", "OSCR"], sorted({record.ticker for record in inclusive_report.records}))

    def test_filters_by_ticker_cluster_status_bucket_regime_and_scanner(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "MDT", [news("Medtronic earnings beat", "2026-06-05T06:30:00-05:00")])
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_catalyst_age_audit_report(
            study_filter=StudyFilter(
                start_date="2026-06-05",
                end_date="2026-06-05",
                ticker="MDT",
                catalyst_cluster="Earnings beat",
                regime="bull",
                scanner="Base Momentum",
                timestamp_status="EXACT_TIMESTAMP",
                age_bucket="<1h",
            ),
            captures_dir=self.captures_dir,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(1, report.total_headlines)
        self.assertEqual("MDT", report.records[0].ticker)


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


def news(headline: str, published_at: str, *, estimated: bool = False) -> dict:
    payload = {"headline": headline, "source": "Fixture", "published_at": published_at, "url": ""}
    if estimated:
        payload["published_at_estimated"] = True
    return payload


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
