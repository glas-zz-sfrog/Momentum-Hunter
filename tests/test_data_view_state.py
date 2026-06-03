from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from momentum_hunter.ui.data_view_state import (
    DataViewState,
    FreshnessSettings,
    get_data_view_style,
)


CENTRAL = ZoneInfo("America/Chicago")


class DataViewStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = FreshnessSettings(
            current_dashboard_warning_minutes=10,
            current_dashboard_stale_minutes=20,
        )
        self.now = datetime(2026, 6, 3, 9, 0, tzinfo=CENTRAL)

    def test_fresh_current_capture_shows_live_banner(self) -> None:
        style = get_data_view_style(
            DataViewState.CURRENT,
            captured_at=self.now - timedelta(minutes=2),
            now=self.now,
            settings=self.settings,
        )
        self.assertIn("CURRENT DASHBOARD - LIVE REVIEW", style.banner_text)
        self.assertEqual("LIVE - ", style.chart_prefix)
        self.assertFalse(style.read_only)

    def test_aging_current_capture_shows_warning(self) -> None:
        style = get_data_view_style(
            DataViewState.CURRENT,
            captured_at=self.now - timedelta(minutes=15),
            now=self.now,
            settings=self.settings,
        )
        self.assertIn("DATA AGING - CONSIDER REFRESH", style.banner_text)
        self.assertTrue(style.is_warning)
        self.assertFalse(style.read_only)

    def test_expired_current_capture_shows_stale_banner(self) -> None:
        style = get_data_view_style(
            DataViewState.CURRENT,
            captured_at=self.now - timedelta(minutes=25),
            now=self.now,
            settings=self.settings,
        )
        self.assertIn("STALE DATA - REFRESH REQUIRED", style.banner_text)
        self.assertEqual("STALE - ", style.chart_prefix)
        self.assertTrue(style.read_only)

    def test_historical_capture_is_read_only(self) -> None:
        style = get_data_view_style(
            DataViewState.HISTORICAL,
            captured_at=self.now - timedelta(days=2),
            session_label="evening",
            now=self.now,
            settings=self.settings,
        )
        self.assertIn("HISTORICAL SNAPSHOT - READ ONLY", style.banner_text)
        self.assertEqual("HISTORICAL - ", style.chart_prefix)
        self.assertTrue(style.read_only)

    def test_study_view_uses_study_prefix(self) -> None:
        style = get_data_view_style(
            DataViewState.STUDY,
            captured_at=None,
            study_run_id="2026-06-03_study",
            source_range="2026-05-01 to 2026-06-01",
            now=self.now,
            settings=self.settings,
        )
        self.assertIn("STUDY RESULTS - SIMULATED HISTORICAL DATA", style.banner_text)
        self.assertEqual("STUDY - ", style.chart_prefix)
        self.assertTrue(style.read_only)


if __name__ == "__main__":
    unittest.main()
