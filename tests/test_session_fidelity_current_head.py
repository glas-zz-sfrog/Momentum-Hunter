from __future__ import annotations

import unittest

from momentum_hunter.session_fidelity_premarket_retry import CHECKPOINTS


class SessionFidelityCurrentHeadTests(unittest.TestCase):
    def test_premarket_retry_preserves_distinct_central_and_eastern_times(self) -> None:
        self.assertEqual(
            tuple(row.target_central.isoformat() for row in CHECKPOINTS.values()),
            (
                "2026-08-12T03:05:00-05:00",
                "2026-08-12T05:55:00-05:00",
                "2026-08-12T06:05:00-05:00",
            ),
        )
        self.assertEqual(
            tuple(row.target_eastern.isoformat() for row in CHECKPOINTS.values()),
            (
                "2026-08-12T04:05:00-04:00",
                "2026-08-12T06:55:00-04:00",
                "2026-08-12T07:05:00-04:00",
            ),
        )


if __name__ == "__main__":
    unittest.main()
