from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.historical_clusters import CLUSTER_RESEARCH_LABEL, build_historical_cluster_report
from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, make_capture_id, save_review_decisions
from momentum_hunter.score_breakdowns import SCORE_ENGINE_VERSION, build_score_breakdown_for_raw_candidate
from momentum_hunter.storage import file_sha256
from momentum_hunter.study import StudyFilter
from momentum_hunter.time_utils import CENTRAL_TZ


class HistoricalClusterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_historical_clusters"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_clusters_are_generated_from_stored_historical_data_only(self) -> None:
        earnings = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "Base Momentum",
            "MDT",
            "Healthcare",
            "Medical Devices",
            96,
            "Medtronic beats earnings and raises guidance",
        )
        ai = capture_payload(
            "2026-06-05T19:00:00-05:00",
            "evening",
            "Institutional Momentum",
            "NVDA",
            "Technology",
            "Semiconductors",
            98,
            "Nvidia AI data center server demand accelerates",
        )
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", earnings)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", ai)
        write_score_store(self.score_path, [earnings, ai], component_label="Stored Component Only")
        write_outcomes(self.outcomes_csv, [earnings, ai], max_gains=["7.5", "11.0"], drawdowns=["-1.0", "-2.5"])
        write_review_decision(self.review_path, earnings, ReviewStatus.WATCHLIST)

        report = build_historical_cluster_report(
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(CLUSTER_RESEARCH_LABEL, report.label)
        self.assertEqual(2, report.total_candidates)
        clusters = {cluster.name: cluster for cluster in report.clusters}
        self.assertIn("Earnings / guidance", clusters)
        self.assertIn("AI infrastructure", clusters)
        self.assertIn("Stored Component Only (1)", clusters["Earnings / guidance"].common_score_components)
        self.assertEqual(["MDT"], clusters["Earnings / guidance"].tickers)
        self.assertEqual(100.0, clusters["Earnings / guidance"].win_rate_pct)

    def test_cluster_build_does_not_mutate_raw_captures(self) -> None:
        payload = capture_payload(
            "2026-06-05T07:00:00-05:00",
            "morning",
            "Base Momentum",
            "MDT",
            "Healthcare",
            "Medical Devices",
            96,
            "Medtronic beats earnings and raises guidance",
        )
        path = self.captures_dir / "2026-06-05" / "morning.json"
        write_capture(path, payload)
        before = file_sha256(path)

        build_historical_cluster_report(
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(before, file_sha256(path))

    def test_quarantined_captures_are_excluded_by_default(self) -> None:
        active = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", "MDT", "Healthcare", "Medical Devices", 96, "Earnings beat")
        quarantined = capture_payload("2026-06-06T07:00:00-05:00", "morning", "Base Momentum", "RXT", "Technology", "Software", 90, "AMD partnership")
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", active)
        write_capture(self.quarantine_dir / "2026-06-06-morning.json", quarantined)

        report = build_historical_cluster_report(
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        tickers = {ticker for cluster in report.clusters for ticker in cluster.tickers}
        self.assertEqual({"MDT"}, tickers)

    def test_non_study_eligible_captures_are_excluded_unless_enabled(self) -> None:
        market_day = capture_payload("2026-06-08T07:00:00-05:00", "morning", "Base Momentum", "MDT", "Healthcare", "Medical Devices", 96, "Earnings beat")
        preopen = capture_payload("2026-06-07T19:00:00-05:00", "preopen", "Base Momentum", "NVDA", "Technology", "Semiconductors", 98, "AI server demand")
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", market_day)
        write_capture(self.captures_dir / "2026-06-07" / "preopen.json", preopen)

        default_report = build_historical_cluster_report(
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        inclusive_report = build_historical_cluster_report(
            study_filter=StudyFilter(include_non_study_eligible=True),
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(1, default_report.total_candidates)
        self.assertEqual(2, inclusive_report.total_candidates)

    def test_missing_outcome_data_warns_without_fake_metrics(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", "MDT", "Healthcare", "Medical Devices", 96, "Earnings beat")
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        report = build_historical_cluster_report(
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        cluster = report.clusters[0]

        self.assertIsNone(cluster.average_max_gain_pct)
        self.assertIsNone(cluster.win_rate_pct)
        self.assertTrue(any("Missing outcome data" in warning for warning in cluster.warnings))
        self.assertTrue(any("Sample size 1" in warning for warning in cluster.warnings))

    def test_cluster_counts_are_deterministic_and_filterable(self) -> None:
        rows = [
            capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", "MDT", "Healthcare", "Medical Devices", 96, "Earnings beat"),
            capture_payload("2026-06-05T19:00:00-05:00", "evening", "Institutional Momentum", "NVDA", "Technology", "Semiconductors", 98, "AI server demand"),
            capture_payload("2026-06-06T07:00:00-05:00", "manual", "Base Momentum", "RXT", "Technology", "Software", 60, "No clear move"),
        ]
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", rows[0])
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", rows[1])
        write_capture(self.captures_dir / "2026-06-06" / "manual.json", rows[2])

        first = build_historical_cluster_report(
            study_filter=StudyFilter(start_date="2026-06-05", end_date="2026-06-05", scanner="Base Momentum", sector="Healthcare", minimum_score=90),
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        second = build_historical_cluster_report(
            study_filter=StudyFilter(start_date="2026-06-05", end_date="2026-06-05", scanner="Base Momentum", sector="Healthcare", minimum_score=90),
            captures_dir=self.captures_dir,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual([(cluster.name, cluster.candidate_count) for cluster in first.clusters], [(cluster.name, cluster.candidate_count) for cluster in second.clusters])
        self.assertEqual(1, first.total_candidates)
        self.assertEqual("Earnings / guidance", first.clusters[0].name)


def capture_payload(capture_time: str, session: str, scanner: str, ticker: str, sector: str, industry: str, score: int, headline: str) -> dict:
    return {
        "schema_version": 2,
        "capture_time": capture_time,
        "capture_date": capture_time[:10],
        "session": session,
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": scanner},
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
                "news": [{"headline": headline, "source": "Fixture", "published_at": capture_time}],
            }
        ],
    }


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_score_store(path: Path, captures: list[dict], *, component_label: str) -> None:
    records = {}
    for capture in captures:
        record = build_score_breakdown_for_raw_candidate(capture, capture["candidates"][0])
        record["components"] = [
            {"key": "stored_only", "label": component_label, "points_after_adjustment": 5},
        ]
        records[record["identity_key"]] = record
    path.write_text(json.dumps({"schema_version": 1, "score_engine_version": SCORE_ENGINE_VERSION, "records": records}, indent=2), encoding="utf-8")


def write_review_decision(path: Path, capture: dict, status: ReviewStatus) -> None:
    scanner = capture["scanner"]["name"]
    ticker = capture["candidates"][0]["ticker"]
    identity = CandidateIdentity(
        capture_id=make_capture_id(capture["capture_date"], capture["session"], capture["provider"], scanner),
        capture_date=capture["capture_date"],
        session=capture["session"],
        provider=capture["provider"],
        scanner=scanner,
        ticker=ticker,
    )
    save_review_decisions(
        {
            identity.key: ReviewDecision(
                identity=identity,
                review_status=status,
                decision_timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=CENTRAL_TZ),
                decision_note="Fixture decision.",
            )
        },
        path=path,
    )


def write_outcomes(path: Path, captures: list[dict], *, max_gains: list[str], drawdowns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        for capture, gain, drawdown in zip(captures, max_gains, drawdowns):
            row = {field: "" for field in OUTCOME_FIELDNAMES}
            candidate = capture["candidates"][0]
            row.update(
                {
                    "capture_date": capture["capture_date"],
                    "capture_time": capture["capture_time"],
                    "session": capture["session"],
                    "provider": capture["provider"],
                    "scanner": capture["scanner"]["name"],
                    "ticker": candidate["ticker"],
                    "score": str(candidate["score"]),
                    "next_day_return_pct": "1.0",
                    "five_day_return_pct": "2.0",
                    "max_gain_pct": gain,
                    "max_drawdown_pct": drawdown,
                    "outcome_status": "complete",
                }
            )
            writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
