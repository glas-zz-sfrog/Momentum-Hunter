"""Deterministic bounded-wait controls for the Science custody client."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter.science_custody_commit import CustodyCommitIntegrityError, CustodyCommitPending
from momentum_hunter.science_custody_mailbox import CustodyPendingRequest
from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet


class ScienceCustodyStartupPollTests(unittest.TestCase):
    @staticmethod
    def pending():
        request = SimpleNamespace(identity=SimpleNamespace(digest=lambda: 'a' * 64))
        return CustodyPendingRequest(request, (1, 2, 3), (1, 2, 4))

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

    def test_absent_completion_hint_avoids_speculative_reconciliation(self):
        now = [0.0]
        hints = []
        calls = []
        result = object()

        def hint(identity):
            hints.append(identity)
            return len(hints) >= 4

        storage = SimpleNamespace(backend=SimpleNamespace(completion_hint=hint),
            client=SimpleNamespace(reconcile=lambda pending: calls.append(pending) or result),
            timeout_seconds=1.0, poll_seconds=0.1,
            _stage=lambda *_: nullcontext())
        with patch('momentum_hunter.science_custody_readonly.time.monotonic', side_effect=lambda: now[0]), \
                patch('momentum_hunter.science_custody_readonly.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            self.assertIs(ScienceCustodyStorageSet._await(storage, self.pending()), result)
        self.assertEqual(['a' * 64] * 4, hints)
        self.assertEqual(1, len(calls))

    def test_hint_never_confers_completion_authority(self):
        for hint_value in (True, None):
            now = [0.0]
            calls = []
            storage = SimpleNamespace(backend=SimpleNamespace(completion_hint=lambda _: hint_value),
                client=SimpleNamespace(reconcile=lambda pending: calls.append(pending) or None),
                timeout_seconds=0.02, poll_seconds=0.01,
                _stage=lambda *_: nullcontext())
            with patch('momentum_hunter.science_custody_readonly.time.monotonic', side_effect=lambda: now[0]), \
                    patch('momentum_hunter.science_custody_readonly.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
                with self.assertRaises(CustodyCommitPending):
                    ScienceCustodyStorageSet._await(storage, self.pending())
            self.assertEqual(3, len(calls))

    def test_absent_hint_still_reconciles_at_deadline(self):
        now = [0.0]
        calls = []
        result = object()
        storage = SimpleNamespace(backend=SimpleNamespace(completion_hint=lambda _: False),
            client=SimpleNamespace(reconcile=lambda pending: calls.append(pending) or result),
            timeout_seconds=0.02, poll_seconds=0.01,
            _stage=lambda *_: nullcontext())
        with patch('momentum_hunter.science_custody_readonly.time.monotonic', side_effect=lambda: now[0]), \
                patch('momentum_hunter.science_custody_readonly.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            self.assertIs(ScienceCustodyStorageSet._await(storage, self.pending()), result)
        self.assertEqual(1, len(calls))

    def test_absent_hint_has_bounded_authoritative_fallback(self):
        now = [0.0]
        calls = []
        result = object()
        storage = SimpleNamespace(backend=SimpleNamespace(completion_hint=lambda _: False),
            client=SimpleNamespace(reconcile=lambda pending: calls.append(now[0]) or result),
            timeout_seconds=3.0, poll_seconds=0.1,
            _stage=lambda *_: nullcontext())
        with patch('momentum_hunter.science_custody_readonly.time.monotonic', side_effect=lambda: now[0]), \
                patch('momentum_hunter.science_custody_readonly.time.sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)):
            self.assertIs(ScienceCustodyStorageSet._await(storage, self.pending()), result)
        self.assertEqual(1, len(calls))
        self.assertGreaterEqual(calls[0], 1.0)
        self.assertLess(calls[0], 1.2)

    def test_present_hint_cannot_hide_integrity_failure(self):
        def reject(_pending):
            raise CustodyCommitIntegrityError('Wrong completion identity')

        storage = SimpleNamespace(backend=SimpleNamespace(completion_hint=lambda _: True),
            client=SimpleNamespace(reconcile=reject),
            timeout_seconds=3.0, poll_seconds=0.1,
            _stage=lambda *_: nullcontext())
        with self.assertRaisesRegex(CustodyCommitIntegrityError, 'Wrong completion identity'):
            ScienceCustodyStorageSet._await(storage, self.pending())


if __name__ == '__main__':
    unittest.main()
