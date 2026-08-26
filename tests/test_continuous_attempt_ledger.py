from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_attempt_ledger import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    ContinuousAttemptLedger,
    ContinuousAttemptLedgerError,
)


NOW = "2026-08-26T14:05:00-04:00"


class ContinuousAttemptLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = ContinuousAttemptLedger(
            self.root,
            runtime_identity="attempt-ledger-test",
            configuration_fingerprint="b" * 64,
        )

    def begin(self):
        return self.ledger.begin(
            runtime_instance_id="instance-1",
            stage="COMPOSITION",
            symbol="aaa",
            opportunity_id="opportunity-1",
            request_id="request-1",
            observed_at=NOW,
            request_cutoff=NOW,
            evidence_known_at=(("quote", NOW),),
            source_fingerprint="a" * 64,
            staging_began=False,
        )

    def test_append_only_history_reconstructs_with_canonical_chronology(self) -> None:
        started = self.begin()
        terminal = self.ledger.finish(
            started,
            runtime_instance_id="instance-1",
            event_type=ATTEMPT_FAILED,
            observed_at=NOW,
            diagnostic_code="SYNTHETIC_FAILURE",
            exception_class="RuntimeError",
            message="bounded failure",
            staging_began=True,
            authoritative_state_changed=False,
        )

        restored = ContinuousAttemptLedger(
            self.root,
            runtime_identity="attempt-ledger-test",
            configuration_fingerprint="b" * 64,
        )

        self.assertEqual((started, terminal), restored.events)
        self.assertEqual("AAA", terminal.symbol)
        self.assertEqual(os.getpid(), terminal.process_id)
        self.assertEqual(started.observed_at, terminal.attempt_started_at)
        self.assertEqual("2026-08-26T18:05:00.000000Z", terminal.observed_at)
        self.assertEqual(
            (("quote", "2026-08-26T18:05:00.000000Z"),),
            terminal.canonical_evidence_known_at,
        )

    def test_conflicting_second_terminal_event_fails_closed(self) -> None:
        started = self.begin()
        self.ledger.finish(
            started,
            runtime_instance_id="instance-1",
            event_type=ATTEMPT_SUCCEEDED,
            observed_at=NOW,
            authoritative_state_changed=True,
        )

        with self.assertRaisesRegex(
            ContinuousAttemptLedgerError, "conflicting evidence"
        ):
            self.ledger.finish(
                started,
                runtime_instance_id="instance-1",
                event_type=ATTEMPT_SUCCEEDED,
                observed_at=NOW,
                diagnostic_code="DIFFERENT",
                authoritative_state_changed=False,
            )

    def test_truncated_or_tampered_history_fails_closed(self) -> None:
        started = self.begin()
        self.ledger.finish(
            started,
            runtime_instance_id="instance-1",
            event_type=ATTEMPT_FAILED,
            observed_at=NOW,
            authoritative_state_changed=False,
        )
        content = self.ledger.path.read_bytes()
        self.ledger.path.write_bytes(content[:-1])
        with self.assertRaisesRegex(
            ContinuousAttemptLedgerError, "incomplete terminal record"
        ):
            ContinuousAttemptLedger(
                self.root,
                runtime_identity="attempt-ledger-test",
                configuration_fingerprint="b" * 64,
            )

    def test_fingerprint_tamper_fails_closed(self) -> None:
        self.begin()
        lines = self.ledger.path.read_text(encoding="ascii").splitlines()
        payload = json.loads(lines[0])
        payload["symbol"] = "BBB"
        self.ledger.path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(
            ContinuousAttemptLedgerError, "fingerprint is invalid"
        ):
            ContinuousAttemptLedger(
                self.root,
                runtime_identity="attempt-ledger-test",
                configuration_fingerprint="b" * 64,
            )

    def test_future_known_evidence_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ContinuousAttemptLedgerError, "after its decision cutoff"
        ):
            self.ledger.begin(
                runtime_instance_id="instance-1",
                stage="READINESS",
                symbol="AAA",
                opportunity_id="opportunity-1",
                request_id="request-future",
                observed_at=NOW,
                request_cutoff=NOW,
                evidence_known_at=(("future", "2026-08-26T18:05:00.000001Z"),),
                source_fingerprint="a" * 64,
                staging_began=False,
            )

    def test_every_attempt_event_is_fsynced_before_return(self) -> None:
        with patch(
            "momentum_hunter.continuous_attempt_ledger.os.fsync"
        ) as sync:
            started = self.begin()
            self.ledger.finish(
                started,
                runtime_instance_id="instance-1",
                event_type=ATTEMPT_SUCCEEDED,
                observed_at=NOW,
                authoritative_state_changed=True,
            )

        self.assertEqual(2, sync.call_count)


if __name__ == "__main__":
    unittest.main()
