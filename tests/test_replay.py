from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.replay import OUTCOME_LABEL, RAW_CAPTURE, REVIEW_DECISION, build_candidate_timeline, build_replay_view_model
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, make_capture_id, save_review_decisions
from momentum_hunter.score_breakdowns import SCORE_ENGINE_VERSION, build_score_breakdown_for_raw_candidate, score_breakdown_identity_key
from momentum_hunter.storage import save_capture_integrity_manifest
from momentum_hunter.time_utils import CENTRAL_TZ


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_replay"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_timeline_orders_multiple_sessions_and_classifies_sources(self) -> None:
        morning = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        evening = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Institutional Momentum", price=84.0, score=94)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", morning)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", evening)
        write_score_store(self.score_path, [morning, evening])
        write_review_decision(self.review_path, morning, "COO")
        write_outcomes(self.outcomes_csv, morning, "COO")

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(["morning", "evening"], [row.session for row in rows])
        self.assertEqual(["Base Momentum", "Institutional Momentum"], [row.scanner for row in rows])
        self.assertIn("2026", rows[0].capture_time_text)
        self.assertEqual(RAW_CAPTURE, rows[0].fields["price"].source)
        self.assertEqual(REVIEW_DECISION, rows[0].fields["review_status"].source)
        self.assertEqual(OUTCOME_LABEL, rows[0].fields["next_day_return_pct"].source)
        self.assertEqual("watchlist", rows[0].fields["review_status"].value)
        self.assertEqual("3.2500", rows[0].fields["next_day_return_pct"].value)

        newest = build_candidate_timeline(
            "COO",
            newest_first=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(["evening", "morning"], [row.session for row in newest])

    def test_replay_view_model_uses_stored_score_breakdown_statuses(self) -> None:
        complete = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=100)
        legacy = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Base Momentum", price=83.0, score=1)
        incomplete = capture_payload("2026-06-06T07:00:00-05:00", "morning", "Institutional Momentum", price=85.0, score=96)
        incomplete["candidates"][0].pop("score_profile")
        incomplete["candidates"][0].pop("relative_volume")
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", complete)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", legacy)
        write_capture(self.captures_dir / "2026-06-06" / "morning.json", incomplete)
        write_score_store(self.score_path, [complete, legacy, incomplete])

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        statuses = [row.score_breakdown["status"] for row in rows]
        self.assertIn("complete", statuses)
        self.assertIn("legacy", statuses)
        self.assertIn("incomplete", statuses)
        self.assertTrue(any("Score breakdown is legacy" in row.warnings for row in rows))
        self.assertTrue(any("Score breakdown is incomplete" in row.warnings for row in rows))
        view_model = build_replay_view_model(rows[0])
        self.assertTrue(view_model.read_only)
        self.assertEqual("Historical Replay - Point-in-Time Snapshot", view_model.banner)

    def test_missing_score_breakdown_and_duplicate_identity_warnings(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        duplicate = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(["Missing stored score breakdown", "Missing later outcome label"], duplicate[0].warnings)

        payload["candidates"].append(dict(payload["candidates"][0]))
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertTrue(all("Duplicate replay identity" in row.warnings for row in rows))

    def test_quarantined_captures_are_excluded_by_default_and_warn_when_visible(self) -> None:
        active = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        quarantined = capture_payload("2026-06-06T07:00:00-05:00", "morning", "Base Momentum", price=88.0, score=91)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", active)
        quarantine_path = self.quarantine_dir / "2026-06-06-morning.json"
        write_capture(quarantine_path, quarantined)
        save_capture_integrity_manifest(
            {
                "schema_version": 2,
                "records": {},
                "quarantined_records": {
                    "captures/2026-06-06/morning.json": {
                        "kind": "raw_capture_json",
                        "capture_date": "2026-06-06",
                        "session": "morning",
                        "provider": "finviz",
                        "scanner": "Base Momentum",
                        "quarantine_path": quarantine_path.resolve().as_posix(),
                    }
                },
            },
            self.manifest_path,
        )

        default_rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(1, len(default_rows))

        visible_rows = build_candidate_timeline(
            "COO",
            include_quarantined=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(2, len(visible_rows))
        quarantined_rows = [row for row in visible_rows if row.quarantined]
        self.assertEqual("Quarantined - Not Trusted for Study Use", quarantined_rows[0].trust_label)
        self.assertIn("Quarantined - Not Trusted for Study Use", quarantined_rows[0].warnings)


def capture_payload(capture_time: str, session: str, scanner: str, *, price: float, score: int) -> dict:
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
                "ticker": "COO",
                "company": "Cool Corp",
                "price": price,
                "percent_change": 6.5,
                "volume": 35_000_000,
                "relative_volume": 2.2,
                "market_cap": 75_000_000_000,
                "sector": "Technology",
                "industry": "Software",
                "score": score,
                "score_profile": "regime-aware-v1",
                "score_regime": "bull",
                "news": [
                    {
                        "headline": "Cool beats earnings and raises AI server guidance",
                        "source": "Finviz",
                        "published_at": capture_time,
                        "url": "",
                        "summary": "",
                    }
                ],
            }
        ],
    }


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_score_store(path: Path, captures: list[dict]) -> None:
    records = {}
    for capture in captures:
        record = build_score_breakdown_for_raw_candidate(capture, capture["candidates"][0])
        records[record["identity_key"]] = record
    path.write_text(json.dumps({"schema_version": 1, "score_engine_version": SCORE_ENGINE_VERSION, "records": records}, indent=2), encoding="utf-8")


def write_review_decision(path: Path, capture: dict, ticker: str) -> None:
    scanner = capture["scanner"]["name"]
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
                review_status=ReviewStatus.WATCHLIST,
                decision_timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=CENTRAL_TZ),
                decision_note="Later user decision.",
            )
        },
        path=path,
    )


def write_outcomes(path: Path, capture: dict, ticker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {field: "" for field in OUTCOME_FIELDNAMES}
    row.update(
        {
            "capture_date": capture["capture_date"],
            "capture_time": capture["capture_time"],
            "session": capture["session"],
            "mode": capture["mode"],
            "provider": capture["provider"],
            "scanner": capture["scanner"]["name"],
            "ticker": ticker,
            "next_day_return_pct": "3.2500",
            "five_day_return_pct": "8.5000",
            "max_gain_pct": "10.0000",
            "max_drawdown_pct": "-2.0000",
            "outcome_status": "complete",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
