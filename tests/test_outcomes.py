from __future__ import annotations

import unittest

from momentum_hunter.outcomes import PriceBar, calculate_outcome


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

    def test_marks_pending_when_future_bars_are_missing(self) -> None:
        row = {"capture_date": "2026-06-01", "price": "100"}
        outcome = calculate_outcome(row, [])

        self.assertEqual("pending_next_day", outcome.status)
        self.assertIsNone(outcome.next_day_return_pct)


if __name__ == "__main__":
    unittest.main()
