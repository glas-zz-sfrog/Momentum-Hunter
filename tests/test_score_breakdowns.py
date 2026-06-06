from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.integrity import (
    DUPLICATE_SCORE_BREAKDOWN,
    FAIL,
    MISSING_SCORE_BREAKDOWN,
    OK,
    QUARANTINED,
    SCORE_BREAKDOWN_INCOMPLETE,
    SCORE_BREAKDOWN_LEGACY,
    WARN,
    audit_score_breakdowns,
    overall_audit_status,
)
from momentum_hunter.models import Candidate, MarketRegime, NewsItem
from momentum_hunter.scoring import SCORE_ENGINE_VERSION, build_score_breakdown, score_candidate
from momentum_hunter.score_breakdowns import (
    build_score_breakdown_for_raw_candidate,
    rebuild_score_breakdowns,
    score_breakdown_identity,
    score_breakdown_identity_key,
)
from momentum_hunter.storage import save_capture_integrity_manifest
from momentum_hunter.time_utils import CENTRAL_TZ


class ScoreBreakdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_score_breakdowns"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.store_path = self.root / "score-breakdowns.json"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_normal_explanation_generation_and_arithmetic(self) -> None:
        now = datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)
        candidate = rich_candidate(now)

        breakdown = build_score_breakdown(candidate, regime=MarketRegime.BULL, now=now)

        self.assertEqual("complete", breakdown["status"])
        self.assertEqual(SCORE_ENGINE_VERSION, breakdown["score_engine_version"])
        self.assertEqual("OK", breakdown["reconciliation_status"])
        self.assertEqual(
            sum(component["points_after_adjustment"] for component in breakdown["components"]),
            breakdown["pre_floor_total"],
        )
        self.assertEqual(breakdown["computed_final_score"], breakdown["final_score"])
        self.assertTrue(any(component["key"] == "market_cap" for component in breakdown["components"]))
        self.assertTrue(any(component["key"].startswith("positive_catalyst.") for component in breakdown["components"]))

    def test_bonus_penalty_cap_and_floor_handling(self) -> None:
        now = datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)
        capped = build_score_breakdown(rich_candidate(now), regime=MarketRegime.BULL, now=now)

        self.assertTrue(capped["caps"][0]["applied"])
        self.assertEqual(100, capped["final_score"])
        self.assertTrue(capped["bonuses"])

        risky = Candidate(
            ticker="RISK",
            price=1.0,
            percent_change=1.0,
            volume=10_000,
            relative_volume=0.1,
            market_cap=500_000_000,
            news=[NewsItem(headline="Company bankruptcy investigation and dilution risk", published_at=now - timedelta(minutes=30))],
        )
        floored = build_score_breakdown(risky, regime=MarketRegime.BEAR, now=now)

        self.assertTrue(floored["floors"][0]["applied"])
        self.assertEqual(0, floored["final_score"])
        self.assertTrue(floored["penalties"])

    def test_rebuild_command_generates_complete_breakdowns_from_raw_captures(self) -> None:
        payload = raw_capture_payload(score=score_candidate(rich_candidate(datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)), MarketRegime.BULL).score)
        write_raw_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        result = rebuild_score_breakdowns(captures_dir=self.captures_dir, output_path=self.store_path)

        self.assertEqual(1, result.total_records)
        self.assertEqual(1, result.counts["complete"])
        store = json.loads(self.store_path.read_text(encoding="utf-8"))
        record = next(iter(store["records"].values()))
        self.assertEqual("COO", record["ticker"])
        self.assertEqual("complete", record["status"])

    def test_score_breakdown_audit_detects_missing_and_duplicate_records(self) -> None:
        payload = raw_capture_payload(score=90)
        write_raw_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        missing_rows = audit_score_breakdowns(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.store_path,
        )
        self.assertTrue(any(row.status == MISSING_SCORE_BREAKDOWN for row in missing_rows))
        self.assertEqual(FAIL, overall_audit_status(missing_rows))

        record = build_score_breakdown_for_raw_candidate(payload, payload["candidates"][0])
        store = {"schema_version": 1, "records": {"one": record, "two": {**record}}}
        self.store_path.write_text(json.dumps(store, indent=2), encoding="utf-8")
        duplicate_rows = audit_score_breakdowns(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.store_path,
        )
        self.assertTrue(any(row.status == DUPLICATE_SCORE_BREAKDOWN for row in duplicate_rows))
        self.assertEqual(FAIL, overall_audit_status(duplicate_rows))

    def test_quarantined_source_legacy_and_incomplete_records_warn(self) -> None:
        payload = raw_capture_payload(score=90)
        record = build_score_breakdown_for_raw_candidate(payload, payload["candidates"][0])
        save_capture_integrity_manifest(
            {
                "schema_version": 2,
                "records": {},
                "quarantined_records": {
                    "captures/2026-06-05/morning.json": {
                        "capture_date": "2026-06-05",
                        "session": "morning",
                        "provider": "finviz",
                        "scanner": "Base Momentum",
                        "quarantine_path": "quarantine/raw-captures/20260606-120000/2026-06-05-morning.json",
                    }
                },
            },
            self.manifest_path,
        )
        self.store_path.write_text(json.dumps({"schema_version": 1, "records": {record["identity_key"]: record}}, indent=2), encoding="utf-8")

        quarantined_rows = audit_score_breakdowns(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.store_path,
        )
        self.assertTrue(any(row.status == QUARANTINED for row in quarantined_rows))
        self.assertEqual(WARN, overall_audit_status(quarantined_rows))

        write_raw_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        legacy = build_score_breakdown_for_raw_candidate(payload, {**payload["candidates"][0], "score": 1})
        incomplete_payload = {**payload, "capture_time": "2026-06-05T19:00:00-05:00", "session": "evening"}
        incomplete_candidate = dict(payload["candidates"][0])
        incomplete_candidate.pop("score_profile")
        incomplete_candidate.pop("relative_volume")
        incomplete_payload["candidates"] = [incomplete_candidate]
        incomplete = build_score_breakdown_for_raw_candidate(incomplete_payload, incomplete_candidate)
        write_raw_capture(self.captures_dir / "2026-06-05" / "evening.json", incomplete_payload)
        self.store_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "records": {
                        legacy["identity_key"]: legacy,
                        incomplete["identity_key"]: incomplete,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        rows = audit_score_breakdowns(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.store_path,
        )
        self.assertTrue(any(row.status == SCORE_BREAKDOWN_LEGACY for row in rows))
        self.assertTrue(any(row.status == SCORE_BREAKDOWN_INCOMPLETE for row in rows))
        self.assertTrue(any(row.status == OK for row in rows) or any(row.status == SCORE_BREAKDOWN_LEGACY for row in rows))
        self.assertEqual(WARN, overall_audit_status(rows))


def rich_candidate(now: datetime) -> Candidate:
    return Candidate(
        ticker="COO",
        company="Cool Corp",
        price=82.0,
        percent_change=9.2,
        volume=35_000_000,
        relative_volume=2.5,
        market_cap=75_000_000_000,
        news=[
            NewsItem(
                headline="Cool beats earnings, raises guidance, announces AI server partnership and FDA update",
                summary="Analysts lift price target after upgrade.",
                published_at=now - timedelta(minutes=20),
            )
        ],
    )


def raw_capture_payload(score: int) -> dict:
    return {
        "schema_version": 2,
        "capture_time": "2026-06-05T07:00:00-05:00",
        "capture_date": "2026-06-05",
        "session": "morning",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "scoring": {"profile": "regime-aware-v1", "regime": "bull"},
        "market": {"regime": "bull", "symbol": "SPY"},
        "candidates": [
            {
                "rank": 1,
                "ticker": "COO",
                "company": "Cool Corp",
                "price": 82.0,
                "percent_change": 9.2,
                "volume": 35_000_000,
                "relative_volume": 2.5,
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
                        "published_at": "2026-06-05T06:30:00-05:00",
                        "url": "",
                        "summary": "",
                    }
                ],
            }
        ],
    }


def write_raw_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
