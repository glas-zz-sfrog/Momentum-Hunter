from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_tradeplan_producer import CurrentMarketEvidence
from momentum_hunter.preserved_provider_replay import (
    PROFILE,
    PreservedFinvizProvider,
    PreservedProviderReplayError,
    PreservedSchwabBoundary,
    ReplayClock,
    load_preserved_provider_replay,
)


EASTERN = ZoneInfo("America/New_York")


class PreservedProviderReplayTests(unittest.TestCase):
    def test_clock_and_discovery_follow_preserved_chronology(self) -> None:
        launch = datetime(2026, 8, 27, 11, 24, tzinfo=EASTERN)
        received = launch + timedelta(seconds=2)
        clock = ReplayClock(launch)
        snapshot = SimpleNamespace(
            snapshot_id="preserved-snapshot",
            fingerprint="a" * 64,
            requested_at=launch,
            received_at=received,
        )
        provider = PreservedFinvizProvider(clock=clock, snapshots=(snapshot,))

        self.assertIs(snapshot, provider.discover_paginated())
        self.assertEqual(received, clock.now())
        self.assertEqual(received.isoformat(), provider.receipts[0]["providerReceivedAt"])
        self.assertEqual(PROFILE, "OFFLINE_PRESERVED_PROVIDER_REPLAY")

    def test_current_quote_honors_request_cutoff_without_network(self) -> None:
        launch = datetime(2026, 8, 27, 11, 24, tzinfo=EASTERN)
        before = self._current("NVDA", launch + timedelta(seconds=1), "before")
        after = self._current("NVDA", launch + timedelta(seconds=4), "after")
        boundary = PreservedSchwabBoundary(
            clock=ReplayClock(launch),
            admissions={
                "NVDA": (
                    (before, launch + timedelta(seconds=1)),
                    (after, launch + timedelta(seconds=4)),
                )
            },
            minute_files={},
            daily_files={},
        )

        selected = boundary.current_evidence(
            "NVDA",
            launch + timedelta(seconds=2),
        )

        self.assertEqual(after.evidence_id, selected.evidence_id)
        self.assertEqual(launch + timedelta(seconds=4), boundary.decision_cutoff())
        self.assertFalse(boundary.auth_health()["networkRequested"])
        with self.assertRaises(PreservedProviderReplayError):
            boundary.current_evidence("CRM", launch)

    def test_unaccepted_package_identity_fails_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unaccepted.zip"
            path.write_bytes(b"not-the-reviewed-packet")
            with self.assertRaisesRegex(
                PreservedProviderReplayError,
                "identity differs",
            ):
                load_preserved_provider_replay(path)

    @staticmethod
    def _current(
        symbol: str,
        receipt: datetime,
        suffix: str,
    ) -> CurrentMarketEvidence:
        return CurrentMarketEvidence(
            evidence_id=f"evidence-{suffix}",
            symbol=symbol,
            provider_timestamp=receipt.isoformat(),
            receipt_timestamp=receipt.isoformat(),
            source_identity="preserved-schwab",
            market_payload_json="{}\n",
            market_payload_fingerprint="b" * 64,
            evidence_fingerprint="c" * 64,
        )


if __name__ == "__main__":
    unittest.main()
