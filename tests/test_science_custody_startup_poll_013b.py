"""Deterministic bounded-wait controls for the Science custody client."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter.science_custody_commit import CustodyCommitPending
from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet


class ScienceCustodyStartupPollTests(unittest.TestCase):
    def test_default_poll_cadence_is_bounded(self):
        self.assertEqual(0.1, ScienceCustodyStorageSet.__init__.__kwdefaults__['poll_seconds'])

    def test_pending_outcome_preserves_deadline_without_busy_reconciliation(self):
        now = [0.0]
        waits = []
        calls = []

        def reconcile(_pending):
            calls.append(now[0])
            return None

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        storage = SimpleNamespace(client=SimpleNamespace(reconcile=reconcile),
                                  timeout_seconds=0.25, poll_seconds=0.1,
                                  _stage=lambda *_: nullcontext())
        with patch('momentum_hunter.science_custody_readonly.time.monotonic', side_effect=lambda: now[0]), \
                patch('momentum_hunter.science_custody_readonly.time.sleep', side_effect=sleep):
            with self.assertRaises(CustodyCommitPending):
                ScienceCustodyStorageSet._await(storage, object())
        self.assertEqual(4, len(calls))
        self.assertEqual(3, len(waits))
        self.assertAlmostEqual(0.25, sum(waits))

    def test_verified_result_returns_without_extra_poll(self):
        calls = []
        result = object()

        def reconcile(_pending):
            calls.append(1)
            return result

        storage = SimpleNamespace(client=SimpleNamespace(reconcile=reconcile),
                                  timeout_seconds=10.0, poll_seconds=0.1,
                                  _stage=lambda *_: nullcontext())
        with patch('momentum_hunter.science_custody_readonly.time.sleep') as sleep:
            self.assertIs(ScienceCustodyStorageSet._await(storage, object()), result)
        self.assertEqual(1, len(calls))
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
