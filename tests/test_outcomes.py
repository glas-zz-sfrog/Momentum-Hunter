from __future__ import annotations

import unittest
from datetime import date

from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.outcomes import PriceBar, calculate_outcome, expected_outcome_session_dates


class OutcomeTests(unittest.TestCase):
    def test_calculates_forward_outcomes(self) -> None:
        row = {"capture_date": "2026-06-01", "price": "100"}
        bars = [
            PriceBar("2026-06-01", high=101, low=99, close=100),
            PriceBar("2026-06-02", high=106, low=98, close=104),
            PriceBar("2026-06-03", high=108, low=101, close=107),
            PriceBar("2026-06-04", high=109, low=103, close=105),
            PriceBar("2026-06-05", high=112, low=104, close=111),
            PriceBar("2026-06-08", high=115, low=102, close=110),
        ]

        outcome = calculate_outcome(row, bars)

        self.assertEqual("complete", outcome.status)
        self.assertEqual(4.0, outcome.next_day_return_pct)
        self.assertEqual(10.0, outcome.five_day_return_pct)
        self.assertEqual(15.0, outcome.max_gain_pct)
        self.assertEqual(-2.0, outcome.max_drawdown_pct)
        self.assertEqual("2026-06-02", outcome.outcome_start_date)
        self.assertEqual("2026-06-08", outcome.outcome_end_date)
        self.assertEqual("2026-06-02", outcome.expected_next_day_session_date)
        self.assertEqual("2026-06-08", outcome.expected_five_day_session_date)
        self.assertEqual("complete", outcome.next_day_outcome_state)
        self.assertEqual("complete", outcome.five_day_outcome_state)

    def test_marks_pending_when_future_bars_are_missing(self) -> None:
        row = {"capture_date": "2026-06-01", "price": "100"}
        outcome = calculate_outcome(row, [], as_of_date=date(2026, 6, 1))

        self.assertEqual("pending_next_day", outcome.status)
        self.assertEqual("pending_not_mature", outcome.next_day_outcome_state)
        self.assertIsNone(outcome.next_day_return_pct)

    def test_marks_provider_missing_when_mature_next_day_bar_is_missing(self) -> None:
        row = {"capture_date": "2026-06-01", "price": "100"}
        outcome = calculate_outcome(row, [], as_of_date=date(2026, 6, 4))

        self.assertEqual("provider_data_missing", outcome.status)
        self.assertEqual("provider_data_missing", outcome.next_day_outcome_state)
        self.assertIn("no price bar for expected next-day session 2026-06-02", outcome.outcome_reason)

    def test_juneteenth_capture_uses_june_22_as_next_outcome_session(self) -> None:
        row = {"capture_date": "2026-06-18", "price": "100"}
        bars = [
            PriceBar("2026-06-18", high=101, low=99, close=100),
            PriceBar("2026-06-22", high=106, low=98, close=104),
            PriceBar("2026-06-23", high=108, low=101, close=107),
        ]

        outcome = calculate_outcome(row, bars, as_of_date=date(2026, 6, 24))

        self.assertEqual("2026-06-22", outcome.expected_next_day_session_date)
        self.assertEqual("2026-06-26", outcome.expected_five_day_session_date)
        self.assertEqual("pending_five_day", outcome.status)
        self.assertEqual("complete", outcome.next_day_outcome_state)
        self.assertEqual("pending_not_mature", outcome.five_day_outcome_state)
        self.assertEqual(4.0, outcome.next_day_return_pct)
        self.assertIsNone(outcome.five_day_return_pct)

    def test_expected_outcome_sessions_skip_juneteenth_weekend_and_preserve_early_close_as_market_day(self) -> None:
        next_day, five_day = expected_outcome_session_dates("2026-06-18")

        self.assertEqual(date(2026, 6, 22), next_day)
        self.assertEqual(date(2026, 6, 26), five_day)
        self.assertTrue(is_market_open_day(date(2026, 11, 27)))


if __name__ == "__main__":
    unittest.main()
