from __future__ import annotations

import tempfile
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.overnight_data_fidelity import OvernightDataFidelityError
from tools.run_overnight_data_fidelity_campaign import (
    _acquire_lock,
    _source_commit,
    campaign_schedule,
)


class OvernightDataFidelityCampaignTests(unittest.TestCase):
    def test_direct_file_invocation_can_resolve_project_package(self) -> None:
        script = Path(__file__).resolve().parents[1] / "tools" / "run_overnight_data_fidelity_campaign.py"
        completed = subprocess.run(
            [sys.executable, "-B", str(script), "--help"],
            cwd=script.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--source-commit", completed.stdout)

    def test_schedule_straddles_required_boundaries_in_eastern_time(self) -> None:
        schedule = campaign_schedule(date(2026, 8, 20))
        by_code = {item.code: item for item in schedule}
        self.assertEqual(15, len(schedule))
        self.assertEqual("2026-08-20T03:55:00-04:00", by_code["BOUNDARY_0355_ET"].target_eastern.isoformat())
        self.assertEqual("2026-08-20T04:00:00-04:00", by_code["BOUNDARY_0400_ET"].target_eastern.isoformat())
        self.assertEqual("2026-08-20T07:05:00-04:00", by_code["PRE_0705_ET"].target_eastern.isoformat())
        self.assertEqual("2026-08-20T09:45:00-04:00", by_code["REGULAR_0945_ET"].target_eastern.isoformat())
        self.assertTrue(by_code["OVERNIGHT_2005_ET"].include_websocket)
        self.assertTrue(by_code["BOUNDARY_0405_ET"].include_finviz)

    def test_targets_are_strictly_ordered(self) -> None:
        targets = [item.target_eastern for item in campaign_schedule(date(2026, 8, 20))]
        self.assertEqual(sorted(targets), targets)
        self.assertEqual(len(targets), len(set(targets)))

    def test_lock_refuses_second_campaign_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "campaign.lock"
            descriptor = _acquire_lock(lock)
            try:
                with self.assertRaises(OvernightDataFidelityError):
                    _acquire_lock(lock)
            finally:
                import os

                os.close(descriptor)

    def test_source_commit_requires_full_sha(self) -> None:
        self.assertEqual("a" * 40, _source_commit("A" * 40))
        with self.assertRaises(OvernightDataFidelityError):
            _source_commit("abc123")


if __name__ == "__main__":
    unittest.main()
