from __future__ import annotations

import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.models import CaptureSession
from momentum_hunter.scheduling import (
    CaptureCalendarStatus,
    SkipReason,
    classify_capture,
    evaluate_automatic_capture,
    is_market_open_day,
    is_preopen_gap_review_day,
)
from momentum_hunter.time_utils import CENTRAL_TZ


class SchedulingPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_scheduling_policy"
        shutil.rmtree(self.root, ignore_errors=True)
        self.captures_dir = self.root / "captures"
        self.captures_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_ordinary_monday_morning_capture(self) -> None:
        decision = self.decision(CaptureSession.MORNING, "2026-06-08T07:00:00-05:00")

        self.assertTrue(decision.should_capture)
        self.assertEqual(CaptureSession.MORNING, decision.capture_session)
        self.assertEqual(CaptureCalendarStatus.MARKET_OPEN_DAY.value, decision.classification.capture_calendar_status)
        self.assertTrue(decision.classification.is_study_eligible)

    def test_ordinary_monday_evening_capture(self) -> None:
        decision = self.decision(CaptureSession.EVENING, "2026-06-08T19:00:00-05:00")

        self.assertTrue(decision.should_capture)
        self.assertEqual(CaptureSession.EVENING, decision.capture_session)
        self.assertTrue(decision.classification.is_study_eligible)

    def test_friday_evening_capture_is_retained(self) -> None:
        decision = self.decision(CaptureSession.EVENING, "2026-06-05T19:00:00-05:00")

        self.assertTrue(decision.should_capture)
        self.assertEqual(CaptureSession.EVENING, decision.capture_session)
        self.assertTrue(decision.classification.is_study_eligible)

    def test_saturday_morning_and_evening_are_skipped(self) -> None:
        morning = self.decision(CaptureSession.MORNING, "2026-06-06T07:00:00-05:00")
        evening = self.decision(CaptureSession.EVENING, "2026-06-06T19:00:00-05:00")

        self.assertFalse(morning.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_MARKET_DAY.value, morning.skip_reason)
        self.assertFalse(evening.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY.value, evening.skip_reason)

    def test_sunday_morning_skipped_and_sunday_evening_preopen_before_monday(self) -> None:
        morning = self.decision(CaptureSession.MORNING, "2026-06-07T07:00:00-05:00")
        evening = self.decision(CaptureSession.EVENING, "2026-06-07T19:00:00-05:00")

        self.assertFalse(morning.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_MARKET_DAY.value, morning.skip_reason)
        self.assertTrue(evening.should_capture)
        self.assertEqual(CaptureSession.PREOPEN, evening.capture_session)
        self.assertEqual(CaptureCalendarStatus.PREOPEN_GAP_REVIEW_DAY.value, evening.classification.capture_calendar_status)
        self.assertFalse(evening.classification.is_study_eligible)

    def test_monday_holiday_preopen_moves_from_sunday_to_monday_evening(self) -> None:
        sunday = self.decision(CaptureSession.EVENING, "2026-09-06T19:00:00-05:00")
        monday_morning = self.decision(CaptureSession.MORNING, "2026-09-07T07:00:00-05:00")
        monday_evening = self.decision(CaptureSession.EVENING, "2026-09-07T19:00:00-05:00")

        self.assertFalse(is_market_open_day(datetime.fromisoformat("2026-09-07").date()))
        self.assertFalse(sunday.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY.value, sunday.skip_reason)
        self.assertFalse(monday_morning.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_MARKET_DAY.value, monday_morning.skip_reason)
        self.assertTrue(monday_evening.should_capture)
        self.assertEqual(CaptureSession.PREOPEN, monday_evening.capture_session)
        self.assertEqual("2026-09-08", monday_evening.classification.next_market_session_date)

    def test_holiday_evening_skips_when_it_is_not_preopen(self) -> None:
        thanksgiving = self.decision(CaptureSession.EVENING, "2026-11-26T19:00:00-06:00")

        self.assertFalse(thanksgiving.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY.value, thanksgiving.skip_reason)

    def test_manual_weekend_capture_is_allowed(self) -> None:
        decision = self.decision(CaptureSession.MANUAL, "2026-06-06T12:00:00-05:00")

        self.assertTrue(decision.should_capture)
        self.assertEqual(CaptureSession.MANUAL, decision.capture_session)
        self.assertEqual(CaptureCalendarStatus.NON_MARKET_DAY.value, decision.classification.capture_calendar_status)
        self.assertFalse(decision.classification.is_study_eligible)

    def test_direct_preopen_request_obeys_preopen_rule(self) -> None:
        valid = self.decision(CaptureSession.PREOPEN, "2026-06-07T19:00:00-05:00")
        invalid = self.decision(CaptureSession.PREOPEN, "2026-06-06T19:00:00-05:00")

        self.assertTrue(valid.should_capture)
        self.assertEqual(CaptureSession.PREOPEN, valid.capture_session)
        self.assertFalse(invalid.should_capture)
        self.assertEqual(SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY.value, invalid.skip_reason)

    def test_duplicate_capture_is_skipped(self) -> None:
        path = self.captures_dir / "2026-06-08"
        path.mkdir(parents=True)
        (path / "morning.json").write_text("{}", encoding="utf-8")

        decision = self.decision(CaptureSession.MORNING, "2026-06-08T07:00:00-05:00")

        self.assertFalse(decision.should_capture)
        self.assertEqual(SkipReason.SKIP_DUPLICATE_CAPTURE.value, decision.skip_reason)

    def test_derived_classification_for_legacy_weekend_capture(self) -> None:
        classification = classify_capture(
            "2026-06-06T07:00:00-05:00",
            "morning",
            capture_date="2026-06-06",
        )

        self.assertEqual(CaptureCalendarStatus.NON_MARKET_DAY.value, classification.capture_calendar_status)
        self.assertFalse(classification.is_market_open_day)
        self.assertFalse(classification.is_study_eligible)

    def test_preopen_gap_rule_identifies_only_day_before_next_open_after_gap(self) -> None:
        self.assertTrue(is_preopen_gap_review_day(datetime.fromisoformat("2026-06-07").date()))
        self.assertFalse(is_preopen_gap_review_day(datetime.fromisoformat("2026-09-06").date()))
        self.assertTrue(is_preopen_gap_review_day(datetime.fromisoformat("2026-09-07").date()))

    def test_gui_and_headless_job_import_same_policy_function(self) -> None:
        import tools.capture_job as capture_job
        import momentum_hunter.app as app

        self.assertIs(app.evaluate_automatic_capture, evaluate_automatic_capture)
        self.assertIs(capture_job.evaluate_automatic_capture, evaluate_automatic_capture)

    def decision(self, session: CaptureSession, value: str):
        return evaluate_automatic_capture(
            session,
            current_time=datetime.fromisoformat(value).astimezone(CENTRAL_TZ),
            captures_dir=self.captures_dir,
        )


if __name__ == "__main__":
    unittest.main()
