from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.integrity import (
    FAIL,
    MISSING,
    MODIFIED,
    OK,
    ORPHANED_DERIVED_RECORD,
    UNTRACKED,
    WARN,
    audit_raw_captures,
    overall_audit_status,
    write_integrity_audit_report,
)
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import BASE_MOMENTUM, Candidate, CaptureSession, MarketRegime, NewsItem, TradingMode
from momentum_hunter.outcomes import update_outcomes
from momentum_hunter.review import CandidateIdentity, ReviewStatus, make_capture_id, upsert_review_decision
from momentum_hunter.scoring import score_candidates
from momentum_hunter.storage import RawCaptureAlreadyExistsError, candidate_from_dict, file_sha256, save_daily_capture, save_watchlist_report
from momentum_hunter.study import build_capture_study
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


class RawCaptureIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_raw_integrity"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.capture_time = datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)
        self.json_path = self.root / "captures" / "2026-06-05" / "morning.json"
        self.report_path = self.root / "captures" / "2026-06-05" / "morning.md"
        self.json_path.parent.mkdir(parents=True)
        self.saved_json, self.saved_report = self.save_test_capture()
        self.original_json_hash = file_sha256(self.saved_json)
        self.original_report_hash = file_sha256(self.saved_report)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_review_updates_do_not_modify_raw_captures(self) -> None:
        identity = CandidateIdentity(
            capture_id=make_capture_id("2026-06-05", "morning", "finviz", "Base Momentum"),
            capture_date="2026-06-05",
            session="morning",
            provider="finviz",
            scanner="Base Momentum",
            ticker="MDT",
        )

        upsert_review_decision(
            {},
            identity,
            ReviewStatus.WATCHLIST,
            note="Decision note lives outside raw capture.",
            path=self.root / "review-decisions.json",
        )

        self.assert_raw_capture_unchanged()

    def test_outcome_updates_do_not_modify_raw_captures(self) -> None:
        capture_csv = self.root / "analysis-captures.csv"
        write_capture_csv(capture_csv)

        update_outcomes(
            capture_path=capture_csv,
            output_path=self.root / "analysis-outcomes.csv",
            session=FakePriceSession(),
        )

        self.assert_raw_capture_unchanged()

    def test_score_recalculation_does_not_modify_raw_captures(self) -> None:
        payload = json.loads(self.saved_json.read_text(encoding="utf-8"))
        candidates = [candidate_from_dict(item) for item in payload["candidates"]]

        score_candidates(candidates, regime=MarketRegime.BULL, now=self.capture_time + timedelta(hours=1))

        self.assert_raw_capture_unchanged()

    def test_historical_snapshot_loading_does_not_mutate_raw_captures(self) -> None:
        payload = json.loads(self.saved_json.read_text(encoding="utf-8"))
        with (
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
        ):
            window = MomentumHunterWindow()
            try:
                window._load_historical_capture(payload)
            finally:
                window.close()
                window.deleteLater()

        self.assert_raw_capture_unchanged()

    def test_study_and_report_generation_do_not_modify_raw_captures(self) -> None:
        capture_csv = self.root / "analysis-captures.csv"
        report_path = self.root / "watchlist-report.md"
        write_capture_csv(capture_csv)
        payload = json.loads(self.saved_json.read_text(encoding="utf-8"))
        candidates = [candidate_from_dict(item) for item in payload["candidates"]]

        build_capture_study(path=capture_csv)
        with patch("momentum_hunter.storage.report_path", return_value=report_path):
            save_watchlist_report(candidates, for_date=self.capture_time)

        self.assertTrue(report_path.exists())
        self.assert_raw_capture_unchanged()

    def test_integrity_audit_detects_modified_raw_capture(self) -> None:
        rows = self.audit()
        self.assertTrue(rows)
        self.assertTrue(all(row.status == OK for row in rows))
        self.assertEqual("PASS", overall_audit_status(rows))

        payload = json.loads(self.saved_json.read_text(encoding="utf-8"))
        payload["candidates"][0]["company"] = "Changed After Capture"
        self.saved_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        rows = self.audit()
        statuses = {row.path: row.status for row in rows}

        self.assertEqual(MODIFIED, statuses[self.manifest_key(self.saved_json)])
        self.assertEqual(FAIL, overall_audit_status(rows))

        csv_path, markdown_path = write_integrity_audit_report(
            rows,
            csv_path=self.root / "raw-capture-integrity-audit.csv",
            markdown_path=self.root / "raw-capture-integrity-audit.md",
        )
        self.assertTrue(csv_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertIn("Overall Status: FAIL", markdown_path.read_text(encoding="utf-8"))

    def test_integrity_audit_detects_missing_raw_capture(self) -> None:
        self.saved_json.unlink()

        rows = self.audit()
        statuses = {row.path: row.status for row in rows}

        self.assertEqual(MISSING, statuses[self.manifest_key(self.saved_json)])
        self.assertEqual(FAIL, overall_audit_status(rows))

    def test_integrity_audit_warns_on_untracked_legacy_capture(self) -> None:
        rows = audit_raw_captures(
            captures_dir=self.root / "captures",
            manifest_path=self.root / "integrity" / "missing_manifest.json",
            analysis_csv=self.root / "missing-analysis.csv",
            outcomes_csv=self.root / "missing-outcomes.csv",
            review_decisions_path=self.root / "missing-review-decisions.json",
        )

        self.assertTrue(any(row.status == UNTRACKED for row in rows))
        self.assertEqual(WARN, overall_audit_status(rows))

    def test_integrity_audit_detects_orphaned_derived_records(self) -> None:
        orphan_csv = self.root / "orphan-analysis-captures.csv"
        write_capture_csv(orphan_csv, capture_date="2026-06-06")

        rows = audit_raw_captures(
            captures_dir=self.root / "captures",
            manifest_path=self.manifest_path,
            analysis_csv=orphan_csv,
            outcomes_csv=self.root / "missing-outcomes.csv",
            review_decisions_path=self.root / "missing-review-decisions.json",
        )

        self.assertTrue(any(row.status == ORPHANED_DERIVED_RECORD for row in rows))
        self.assertEqual(FAIL, overall_audit_status(rows))

    def test_raw_capture_write_refuses_existing_capture_files(self) -> None:
        with self.assertRaises(RawCaptureAlreadyExistsError):
            self.save_test_capture()

        self.assert_raw_capture_unchanged()

    def save_test_capture(self) -> tuple[Path, Path]:
        with (
            patch("momentum_hunter.storage.capture_json_path", return_value=self.json_path),
            patch("momentum_hunter.storage.capture_report_path", return_value=self.report_path),
            patch("momentum_hunter.storage.CAPTURE_INTEGRITY_MANIFEST", self.manifest_path),
            patch("momentum_hunter.storage.append_analysis_rows", lambda payload: None),
        ):
            return save_daily_capture(
                candidates=[test_candidate()],
                selected_tickers=set(),
                reviewed_tickers=set(),
                criteria=BASE_MOMENTUM,
                provider="finviz",
                mode=TradingMode.PAPER,
                session=CaptureSession.MORNING,
                market_regime=MarketRegimeSnapshot(MarketRegime.BULL, "SPY"),
                capture_time=self.capture_time,
            )

    def audit(self):
        return audit_raw_captures(
            captures_dir=self.root / "captures",
            manifest_path=self.manifest_path,
            analysis_csv=self.root / "missing-analysis.csv",
            outcomes_csv=self.root / "missing-outcomes.csv",
            review_decisions_path=self.root / "missing-review-decisions.json",
        )

    def assert_raw_capture_unchanged(self) -> None:
        self.assertEqual(self.original_json_hash, file_sha256(self.saved_json))
        self.assertEqual(self.original_report_hash, file_sha256(self.saved_report))

    def manifest_key(self, path: Path) -> str:
        return path.resolve().relative_to((Path.cwd() / "MomentumHunterData" / "data").resolve()).as_posix()


def test_candidate() -> Candidate:
    return Candidate(
        ticker="MDT",
        company="Medtronic PLC",
        price=82.0,
        percent_change=5.5,
        volume=19_000_000,
        relative_volume=1.7,
        market_cap=105_000_000_000,
        sector="Healthcare",
        industry="Medical Devices",
        news=[
            NewsItem(
                headline="Medtronic beats earnings expectations",
                source="Finviz",
                published_at=datetime(2026, 6, 5, 6, 30, tzinfo=CENTRAL_TZ),
            )
        ],
        score=90,
        score_reasons=["earnings catalyst"],
    )


def write_capture_csv(path: Path, capture_date: str = "2026-06-05") -> None:
    fieldnames = [
        "capture_date",
        "capture_time",
        "session",
        "mode",
        "provider",
        "scanner",
        "market_regime",
        "rank",
        "selected",
        "reviewed",
        "ticker",
        "company",
        "score",
        "news_hours_old",
        "freshness",
        "freshness_score",
        "article_count",
        "valid_timestamp_count",
        "known_timestamp_count",
        "unknown_timestamp_count",
        "future_timestamp_count",
        "excluded_from_scoring_count",
        "latest_article_age_hours",
        "oldest_article_age_hours",
        "news_range",
        "freshest_headline",
        "score_profile",
        "score_regime",
        "price",
        "percent_change",
        "volume",
        "relative_volume",
        "sector",
        "industry",
    ]
    row = {field: "" for field in fieldnames}
    row.update(
        {
            "capture_date": capture_date,
            "capture_time": f"{capture_date}T07:00:00-05:00",
            "session": "morning",
            "provider": "finviz",
            "scanner": "Base Momentum",
            "market_regime": "bull",
            "ticker": "MDT",
            "company": "Medtronic PLC",
            "score": "90",
            "price": "82.0",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


class FakePriceSession:
    def get(self, url: str, timeout: int):
        return FakePriceResponse()


class FakePriceResponse:
    status_code = 200

    def json(self) -> dict:
        timestamps = [1780704000, 1780963200, 1781049600, 1781136000, 1781222400]
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "close": [84.0, 85.0, 86.0, 87.0, 88.0],
                                    "high": [85.0, 86.0, 87.0, 88.0, 89.0],
                                    "low": [81.0, 82.0, 83.0, 84.0, 85.0],
                                }
                            ],
                            "adjclose": [{"adjclose": [84.0, 85.0, 86.0, 87.0, 88.0]}],
                        },
                    }
                ]
            }
        }


if __name__ == "__main__":
    unittest.main()
