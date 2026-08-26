from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_time_identity import (
    ContinuousTimeIdentityError,
    canonical_instant,
    canonical_known_at,
    chronology_fingerprint,
)


class ContinuousTimeIdentityTests(unittest.TestCase):
    def test_equivalent_central_eastern_and_utc_instants_share_identity(self) -> None:
        values = (
            "2026-08-26T12:22:09.376636-05:00",
            "2026-08-26T13:22:09.376636-04:00",
            "2026-08-26T17:22:09.376636Z",
        )

        self.assertEqual(
            {"2026-08-26T17:22:09.376636Z"},
            {canonical_instant(value) for value in values},
        )

    def test_one_microsecond_changes_identity_and_fingerprint(self) -> None:
        first = "2026-08-26T17:22:09.376636Z"
        second = "2026-08-26T17:22:09.376637Z"

        self.assertNotEqual(canonical_instant(first), canonical_instant(second))
        self.assertNotEqual(
            chronology_fingerprint(
                "test", decision_cutoff=first, evidence_known_at=(("quote", first),)
            ),
            chronology_fingerprint(
                "test", decision_cutoff=second, evidence_known_at=(("quote", second),)
            ),
        )

    def test_equivalent_offsets_produce_stable_chronology_fingerprint(self) -> None:
        central = "2026-08-26T12:22:09.376636-05:00"
        eastern = "2026-08-26T13:22:09.376636-04:00"

        self.assertEqual(
            chronology_fingerprint(
                "test",
                decision_cutoff=central,
                evidence_known_at=(("quote", eastern),),
            ),
            chronology_fingerprint(
                "test",
                decision_cutoff=eastern,
                evidence_known_at=(("quote", central),),
            ),
        )

    def test_known_at_identity_is_label_order_independent(self) -> None:
        first = "2026-08-26T17:22:09Z"
        second = "2026-08-26T17:22:08Z"

        self.assertEqual(
            canonical_known_at((("z", first), ("a", second))),
            canonical_known_at((("a", second), ("z", first))),
        )

    def test_naive_malformed_and_duplicate_chronology_fail_closed(self) -> None:
        with self.assertRaises(ContinuousTimeIdentityError):
            canonical_instant("2026-08-26T17:22:09")
        with self.assertRaises(ContinuousTimeIdentityError):
            canonical_instant("2026-08-26T17:22:09+25:00")
        with self.assertRaises(ContinuousTimeIdentityError):
            canonical_known_at(
                (("quote", "2026-08-26T17:22:09Z"), ("quote", "2026-08-26T17:22:09Z"))
            )

    def test_daylight_and_standard_time_examples_normalize_correctly(self) -> None:
        central = ZoneInfo("America/Chicago")
        eastern = ZoneInfo("America/New_York")
        summer = datetime(2026, 8, 26, 12, 0, tzinfo=central)
        winter = datetime(2026, 1, 26, 12, 0, tzinfo=central)

        self.assertEqual(
            canonical_instant(summer), canonical_instant(summer.astimezone(eastern))
        )
        self.assertEqual(
            canonical_instant(winter), canonical_instant(winter.astimezone(eastern))
        )


if __name__ == "__main__":
    unittest.main()
