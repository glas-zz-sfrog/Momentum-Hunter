"""004 offline operation-boundary, derived-state and complexity regressions."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.strategy_science_continuous_recorder import (
    ContinuousScienceRecorder, ContinuousRecorderError, SimulatedContinuousCrash,
)
from momentum_hunter.strategy_science_recorder.incremental_state import StreamHeads, PublicHistory
from momentum_hunter.strategy_science_recorder.namespace_changes import NamespaceRecoveryRequired
from momentum_hunter.strategy_science_recorder.verified_reads import VerifiedReadError
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_v1, sha256_hex
from momentum_hunter.strategy_science_recorder.custody import RecorderRecoveryError
from momentum_hunter.strategy_science_recorder.coverage import CoverageReconciliationError
from momentum_hunter.strategy_science_source_reader import StrategyScienceSourceReaderV2, SourceReaderCursorError
from tests.test_strategy_science_continuous_recorder import core_fixtures, publication, TickingClock
from tests.test_strategy_science_recorder_contract import (
    SOURCE_ROOT_IDENTITY, identity, health_payload, outcome_attachment, stored_records,
)
from tests.test_strategy_science_recorder_eligibility_authority import export_envelope_v2, v2_outcome_payload


class IncrementalStateTests(unittest.TestCase):
    def test_persistent_heads_sorted_balance_and_old_snapshots(self):
        heads = StreamHeads()
        snapshots = []
        for number in range(2048):
            if number % 127 == 0:
                snapshots.append((number, heads))
            heads = heads.set(f'{number:05d}', (number, str(number)))
        self.assertEqual(2048, len(heads))
        self.assertEqual(sorted(heads), list(heads))
        for length, prior in snapshots:
            self.assertEqual(length, len(prior))
            self.assertEqual(list(range(length)), [prior[key][0] for key in prior])
        replacement = heads.set('00015', (9999, 'replacement'))
        self.assertEqual((15, '15'), heads['00015'])
        self.assertEqual((9999, 'replacement'), replacement['00015'])
        def audit(node):
            if node is None:
                return 0, 0
            left_h, left_n = audit(node[2])
            right_h, right_n = audit(node[3])
            self.assertLessEqual(abs(left_h-right_h), 1)
            self.assertEqual(1+max(left_h, right_h), node[4])
            self.assertEqual(1+left_n+right_n, node[5])
            return node[4], node[5]
        height, size = audit(heads._root)
        self.assertLessEqual(height, 12)
        self.assertEqual(2048, size)

    def test_public_history_snapshot_and_detached_nested_values(self):
        source = [{'x': [1]}]
        first = PublicHistory(source)
        source.append({'x': [2]})
        second = PublicHistory(source)
        first[0]['x'].append(999)
        self.assertEqual([{'x': [1]}], list(first))
        self.assertEqual([{'x': [1]}, {'x': [2]}], list(second))
        self.assertEqual([{'x': [1]}], list(second[:1]))


@unittest.skipUnless(os.name == 'nt', '004 native coherence requires Windows.')
class IncrementalOperationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='science004-operations-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.published = self.root/'producer'/'published'
        self.published.mkdir(parents=True)
        self.clock = TickingClock()

    def open(self):
        recorder = ContinuousScienceRecorder(self.published, self.root/'science',
            source_root_identity=SOURCE_ROOT_IDENTITY, writer_instance_id='science004-test', clock=self.clock)
        self.addCleanup(recorder.close)
        return recorder

    def populate(self):
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.published, raw, ordinal)
        recorder = self.open()
        recorder.poll()
        return recorder

    def extra(self, ordinal):
        raw = export_envelope_v2('PROVIDER_HEALTH', health_payload(
            health_id=identity('PROVIDER_HEALTH_EVENT_ID', f'incremental-{ordinal}')),
            stream_id=f'health-incremental-{ordinal}', event_id=f'health-{ordinal}')
        return publication(self.published, raw, ordinal)

    def compare(self, recorder, fast):
        full = recorder.coverage()
        for key in full:
            if key in fast:
                self.assertEqual(full[key], fast[key], key)

    def test_each_family_and_later_outcome_incremental_equals_full_audit(self):
        recorder = self.open()
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.published, raw, ordinal)
            result = recorder.poll(max_items=1)
            self.compare(recorder, result['coverage'])
        attachment = outcome_attachment(v2_outcome_payload(recorder.custody_root))
        result = recorder.append_outcome(attachment)
        self.assertEqual('ACCEPTED', result['status'])
        self.compare(recorder, recorder.poll()['coverage'])
        self.assertEqual('IDEMPOTENT_ACK', recorder.append_outcome(attachment)['status'])
        self.compare(recorder, recorder.poll()['coverage'])

    def test_normal_new_facts_and_empty_polls_cannot_call_history_audits(self):
        recorder = self.populate()
        views = recorder.recorder._views
        before = dict(views.counters)
        producer_before = recorder._support.counters['producer_full_inventories']
        with ExitStack() as stack:
            for target, name in ((views, '_inventory'), (views.reads, 'audit_known'),
                    (recorder._ledger_reads, 'audit_known'), (recorder.recorder, 'verify'),
                    (recorder, 'records'), (recorder._support, '_baseline_producer'),
                    (StrategyScienceSourceReaderV2, '_load_state')):
                stack.enter_context(patch.object(target, name, side_effect=AssertionError('Normal history scan: '+name)))
            for ordinal in range(6, 26):
                self.extra(ordinal)
                result = recorder.poll(max_items=1)
                self.assertEqual(1, result['admitted'])
                self.assertEqual(0, recorder.poll(max_items=1)['admitted'])
        self.assertEqual(before['namespace_audits'], views.counters['namespace_audits'])
        self.assertEqual(producer_before, recorder._support.counters['producer_full_inventories'])
        self.compare(recorder, result['coverage'])

    def test_same_instance_crash_keeps_unprocessed_publications_reachable(self):
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.published, raw, ordinal)
        recorder = self.open()
        with self.assertRaises(SimulatedContinuousCrash):
            recorder.poll(crash_phase='after_arrival')
        result = recorder.poll()
        self.assertEqual(5, result['coverage']['admitted_arrival_count'])
        self.assertEqual(0, result['coverage']['pending_count'])
        self.assertEqual(0, recorder.poll()['admitted'])
        self.compare(recorder, result['coverage'])

    def test_old_producer_write_racing_new_admission_fails_boundary_and_retains_raw(self):
        recorder = self.populate()
        old = next(self.published.iterdir())
        original = old.read_bytes()
        changed = original+b' '
        self.extra(6)
        original_check = recorder.reader._check_cursor
        calls = 0
        def mutate_once():
            nonlocal calls
            calls += 1
            # The cursor's closing check runs after the new receipt/admission.
            result = original_check()
            if calls == 1:
                old.write_bytes(changed)
            return result
        with patch.object(recorder.reader, '_check_cursor', side_effect=mutate_once):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll()
        arrivals = recorder.arrivals()
        retained = [recorder.raw_bytes(row['arrival_id']) for row in arrivals]
        self.assertIn(original, retained)
        self.assertIn(changed, retained)
        self.assertTrue(recorder.coverage()['admission_frozen'])

    def test_unknown_custody_file_and_overflow_never_become_normal_empty_inventory(self):
        recorder = self.populate()
        with patch.object(recorder.recorder._views.changes, 'drain',
                side_effect=NamespaceRecoveryRequired('SYNTHETIC_OVERFLOW_REQUIRES_AUDIT')):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll()
        self.assertEqual(5, recorder.coverage()['admitted_arrival_count'])
        unexpected = self.root/'science'/'custody'/'sessions'/'unknown.json'
        unexpected.write_bytes(b'{}')
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()

    def test_deleted_old_cursor_and_derived_event_ahead_fail_closed(self):
        recorder = self.populate()
        recorder._support.event_count = len(recorder._events)+1
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()
        recorder.close()
        recorder = self.open()
        path = next(iter(recorder.reader._cursor_paths))
        path.unlink()
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()

    def test_restart_first_normal_poll_does_not_rescan_producer(self):
        recorder = self.populate()
        recorder.close()
        recorder = self.open()
        counts = dict(recorder._support.counters)
        with patch.object(recorder._support, '_baseline_producer', side_effect=AssertionError('restart leaked into normal')):
            self.assertEqual(0, recorder.poll()['observed'])
        self.assertEqual(counts['producer_names_visited'], recorder._support.counters['producer_names_visited'])

    def test_new_cursor_binding_fault_matrix_and_exact_delta_pairing(self):
        recorder = self.open()
        captured = []
        original = recorder.reader._cursor_committed
        def capture(*args):
            captured.append(args)
            return original(*args)
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.published, raw, ordinal)
        with patch.object(recorder.reader, '_cursor_committed', side_effect=capture):
            recorder.poll()
        path, raw, envelope, custody, previous = captured[-1]
        actual = json.loads(raw)
        mutations = {field: 'f'*64 for field in ('custody_checkpoint_sha256', 'previous_reader_cursor_sha256',
            'previous_source_envelope_sha256', 'source_envelope_sha256', 'source_publication_identity_sha256')}
        mutations.update({field: actual[field]+'-WRONG' for field in ('publication_file','source_event_id',
            'source_stream_id','source_owner_identity','source_interface_identity')})
        mutations.update(publication_ordinal=actual['publication_ordinal']+1, source_sequence=actual['source_sequence']+1,
            source_effective_known_at='2026-09-02T13:30:00Z', source_emitted_at='2026-09-02T13:30:00Z',
            session_id=dict(actual['session_id'], authority='WRONG'), custody_status='IDEMPOTENT_ACK',
            manifest_phase='START', final_disposition='COMPLETE_SOURCE_FINAL', terminal=True,
            schema_version='1.0.0', execution_authority='PAPER', reader_version='WRONG')
        for field, value in mutations.items():
            changed = dict(actual, **{field: value})
            changed_raw = canonical_json_v1(changed)
            changed_path = path.parent/f"{changed['publication_ordinal']:020d}-{sha256_hex(changed_raw)}.reader-cursor.json"
            # Isolate validation of a valid-looking installed postimage: use an
            # exact matching hash/name, not merely a filename mismatch failure.
            with self.subTest(field=field), recorder.recorder._views.incremental_operation(), \
                    patch.object(recorder.reader._cursor_reads, 'read', return_value=changed_raw), \
                    self.assertRaises(SourceReaderCursorError):
                original(changed_path, changed_raw, envelope, custody, previous)
        for replacement in (replace(custody, record_ids=('f'*64,)),
                replace(custody, checkpoint_sha256='f'*64), replace(custody, source_sequence=999),
                replace(custody, source_event_id='WRONG')):
            with recorder.recorder._views.incremental_operation(), self.assertRaises(RecorderRecoveryError):
                recorder.recorder.verify_commit_delta(envelope, replacement)

    def test_poisoned_json_and_coverage_counts_never_override_raw_authority(self):
        recorder = self.populate()
        recorder._support.coverage.families['candidate-observation'] += 1
        with self.assertRaises(CoverageReconciliationError):
            recorder.poll()
        recorder.close()
        recorder = self.open()
        views = recorder.recorder._views
        path = next(p for p in views.json if p.name.endswith('.payload.json'))
        cached = views.json[path]
        # Canonical reserialization must catch a mutated parsed cache value
        # even with unchanged disk bytes and R generation.
        cached['record_type'] = 'POISONED'
        with self.assertRaises((ContinuousRecorderError, RecorderRecoveryError)):
            recorder.coverage()
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()

    def test_read_only_after_interruption_does_not_create_recovery_records(self):
        publication(self.published, core_fixtures()[0], 1)
        recorder = self.open()
        with self.assertRaises(SimulatedContinuousCrash):
            recorder.poll(crash_phase='after_arrival')
        before = {p: p.read_bytes() for p in recorder.custody_root.rglob('*.payload.json')}
        recorder.arrivals()
        recorder.coverage()
        recorder.records()
        self.assertEqual(before, {p: p.read_bytes() for p in recorder.custody_root.rglob('*.payload.json')})


if __name__ == '__main__':
    unittest.main()
