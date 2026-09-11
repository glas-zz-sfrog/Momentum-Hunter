from __future__ import annotations

import copy
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from momentum_hunter import continuous_runtime as runtime
from tests.writer_backlog_gate import (
    BOUNDS, CAPACITY, DEFAULT_EVIDENCE, EVIDENCE_ENV, BacklogGateError,
    checked_path, load_trial, qualify_trial, replay_actual_queue, verify_custody,
)
from tests.writer_backlog_readmission import qualify, verify_for_current_source


class ProductionGroundedBacklogGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ.get(EVIDENCE_ENV, DEFAULT_EVIDENCE))
        cls.source = Path(__file__).resolve().parents[1]
        verify_for_current_source(cls.root, cls.source)
        cls.trials = {name:load_trial(cls.root, name) for name in BOUNDS}

    def mutated(self, name):
        return copy.deepcopy(self.trials[name])

    @staticmethod
    def rehash_checkpoint(trial):
        cp = trial.checkpoint
        cp['checkpoint_fingerprint'] = runtime._fingerprint('continuous-runtime-checkpoint-v1',
            {k:v for k,v in cp.items() if k != 'checkpoint_fingerprint'})

    def test_all_six_accepted_physical_trials_pass_current_actual_queue(self):
        report = qualify(self.root, self.source)
        self.assertEqual('PASS', report['status'])
        self.assertEqual(1550, sum(t['admissions'] for t in report['trials']))
        self.assertEqual(1294, sum(t['durable'] for t in report['trials']))
        self.assertEqual(256, sum(t['pending'] for t in report['trials']))
        self.assertTrue(all(t['replayMatchesActual'] for t in report['trials']))
        self.assertFalse(report['installedOrUnboundedReadiness'])

    def test_wrong_queue_capacity_fails(self):
        with self.assertRaisesRegex(BacklogGateError, 'WRONG_QUEUE_CAPACITY'):
            replay_actual_queue(self.trials['EXPECTED'].events, 128)

    def test_actual_queue_operations_not_a_modeled_peak_substitute(self):
        with patch.object(runtime.BoundedWorkQueue, 'pop', return_value=None):
            with self.assertRaisesRegex(BacklogGateError, 'REPLAY_FIFO_MISMATCH'):
                qualify_trial(self.trials['EXPECTED'])

    def test_valid_physical_wave_above_wrong_finite_bound_fails(self):
        trial = replace(self.trials['PEAK'], name='EXPECTED')
        with self.assertRaisesRegex(BacklogGateError, 'FINITE_QUEUE_ENVELOPE_EXCEEDED'):
            qualify_trial(trial)

    def test_replay_disagrees_with_measured_depth_fails(self):
        trial = self.mutated('EXPECTED')
        next(e for e in trial.events if e['kind']=='DEPARTURE')['metrics']['current_depth'] += 1
        with self.assertRaisesRegex(BacklogGateError, 'REPLAY_DEPTH_MISMATCH'):
            qualify_trial(trial)

    def test_missing_admission_receipt_fails(self):
        trial = self.mutated('EXPECTED')
        missing = next(e for e in trial.events if e['kind']=='ARRIVAL')
        trial.events.remove(missing)
        for index, event in enumerate(trial.events, 1):
            event['eventIndex'] = index
        with self.assertRaisesRegex(BacklogGateError, 'MISSING_ADMISSION_RECEIPT'):
            qualify_trial(trial)

    def test_lost_durable_record_fails(self):
        trial = self.mutated('EXPECTED')
        trial.records.pop(next(iter(trial.records)))
        with self.assertRaisesRegex(BacklogGateError, 'LOST_DURABLE_RECORD'):
            qualify_trial(trial)

    def test_checkpoint_count_mismatch_fails_even_with_valid_fingerprint(self):
        trial = self.mutated('EXPECTED')
        trial.checkpoint['sequence'] += 1
        self.rehash_checkpoint(trial)
        with self.assertRaisesRegex(BacklogGateError, 'CHECKPOINT_COUNT_MISMATCH'):
            qualify_trial(trial)

    def test_transient_backlog_beyond_existing_120s_recovery_budget_fails(self):
        trial = self.mutated('TRANSIENT')
        last_slow = max(e['eventIndex'] for e in trial.events if e['kind']=='SERVICE_END'
                        and e['result']['acknowledgement_seconds'] > .5)
        for event in trial.events:
            if event['eventIndex'] > last_slow:
                event['monotonic'] += 121
        with self.assertRaisesRegex(BacklogGateError, 'TRANSIENT_RECOVERY_BUDGET'):
            qualify_trial(trial)

    def test_transient_unfinished_pending_queue_fails(self):
        trial = self.mutated('TRANSIENT')
        final = max(e['eventIndex'] for e in trial.events if e['kind']=='DEPARTURE')
        trial.events = [e for e in trial.events if e['eventIndex'] != final]
        for index, event in enumerate(trial.events, 1):
            event['eventIndex'] = index
        with self.assertRaises(BacklogGateError):
            qualify_trial(trial)

    def test_persistent_overload_not_failed_terminal_is_rejected(self):
        trial = self.mutated('PERSISTENT')
        trial.events[-1]['state'] = 'RUNNING'
        with self.assertRaisesRegex(BacklogGateError, 'OVERLOAD_FAILURE_NOT_PRESERVED'):
            qualify_trial(trial)

    def test_restart_cannot_clear_overload_checkpoint(self):
        trial = self.mutated('PERSISTENT')
        trial.checkpoint['process_state'] = 'RUNNING'
        self.rehash_checkpoint(trial)
        with self.assertRaisesRegex(BacklogGateError, 'OVERLOAD_FAILURE_NOT_PRESERVED'):
            qualify_trial(trial)

    def test_restart_cannot_lose_pending_identity(self):
        trial = self.mutated('PERSISTENT')
        snapshots = [e for e in trial.events if e['kind']=='QUEUE_SNAPSHOT']
        snapshots[-1]['intents'].pop()
        with self.assertRaisesRegex(BacklogGateError, 'RESTART_QUEUE_MISMATCH'):
            qualify_trial(trial)

    def test_capacity_and_finite_bounds_are_accepted_not_generic_defaults(self):
        self.assertEqual(256, CAPACITY)
        self.assertEqual({'EXPECTED':2,'PEAK':122,'SAFETY_STRESS':244,'TRANSIENT':122,'PERSISTENT':256,'ROLLOVER':2}, BOUNDS)
        self.assertLess(BOUNDS['SAFETY_STRESS'], CAPACITY)

    def test_missing_custody_never_skips_or_accepts(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                qualify(Path(temporary), self.source)

    def test_altered_freeze_fails_before_evidence_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'REVIEW-FREEZE.json').write_bytes(b'{}')
            with self.assertRaisesRegex(BacklogGateError, 'UNACCEPTED_FREEZE'):
                verify_custody(root, self.source)

    def test_altered_review_fails_before_evidence_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'REVIEW-FREEZE.json').write_bytes((self.root/'REVIEW-FREEZE.json').read_bytes())
            (root/'ASTRA-REVIEW.json').write_bytes(b'{}')
            with self.assertRaisesRegex(BacklogGateError, 'UNACCEPTED_REVIEW'):
                verify_custody(root, self.source)

    def test_changed_runtime_bytes_invalidate_prior_physical_custody(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source/'momentum_hunter').mkdir()
            (source/'momentum_hunter'/'continuous_runtime.py').write_bytes(b'# changed runtime')
            with self.assertRaisesRegex(BacklogGateError, 'RUNTIME_INPUT_CHANGED'):
                verify_custody(self.root, source)

    def test_manifest_path_escape_fails(self):
        for name in ('../outside','C:/outside','/absolute'):
            with self.subTest(name=name), self.assertRaises(BacklogGateError):
                checked_path(self.root, name)

    def test_v2_authority_change_fails(self):
        import json
        trial = self.mutated('EXPECTED')
        name = next(iter(trial.publications))
        value = json.loads(trial.publications[name])
        value['execution_authority'] = 'ORDERS'
        trial.publications[name] = json.dumps(value).encode()
        with self.assertRaisesRegex(BacklogGateError, 'V2_AUTHORITY'):
            qualify_trial(trial)
