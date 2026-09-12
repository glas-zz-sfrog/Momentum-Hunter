"""Science005 native custody closure; disposable synthetic roots, no activation."""
from contextlib import ExitStack
import ctypes
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.strategy_science_continuous_recorder import (
    ContinuousScienceRecorder, ContinuousRecorderError,
)
from momentum_hunter.strategy_science_recorder.namespace_changes import (
    DirectoryChanges, NamespaceRecoveryRequired,
)
from momentum_hunter.strategy_science_recorder.custody import RecorderRecoveryError
from momentum_hunter.strategy_science_recorder.reusable_views import ReusableViews
from momentum_hunter.strategy_science_recorder.continuous_incremental import ContinuousIncremental
from momentum_hunter.strategy_science_recorder.verified_reads import (
    VerifiedReadError, _unretired_requests,
)
from momentum_hunter.strategy_science_source_reader import (
    StrategyScienceSourceReaderV2, SourceReaderCursorError, SourceReaderPublicationError,
)
from tests.test_strategy_science_continuous_recorder import core_fixtures, publication, TickingClock
from tests.test_strategy_science_recorder_contract import (
    SOURCE_ROOT_IDENTITY, discovery_payload, observation, identity, health_payload,
)
from tests.test_strategy_science_recorder_eligibility_authority import export_envelope_v2


def immutable(root):
    return {p.relative_to(root):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.name.endswith('.json')}


def name_storm(root, count=600):
    """Real Windows file-name events, no synthetic overflow exception."""
    for number in range(count):
        path = root / (f'probe-{number:05d}-'+'x'*100)
        path.write_bytes(b'synthetic transient, not evidence')
        moved = path.with_name(path.name+'-moved')
        path.rename(moved)
        moved.unlink()


@unittest.skipUnless(os.name == 'nt', 'Science005 requires native Windows notifications')
class NamespaceClosure005Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='N005-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.publication = self.root/'producer/published'
        self.publication.mkdir(parents=True)
        self.science = self.root/'science'
        self.clock = TickingClock()

    def opened(self):
        value = ContinuousScienceRecorder(self.publication,self.science,
            source_root_identity=SOURCE_ROOT_IDENTITY,writer_instance_id='N005-synthetic',clock=self.clock)
        self.addCleanup(value.close)
        return value

    def started(self):
        publication(self.publication,core_fixtures()[0],1)
        recorder = self.opened()
        self.assertEqual(1,recorder.poll(max_items=1)['admitted'])
        return recorder

    def populated(self):
        for ordinal,raw in enumerate(core_fixtures(),1):
            publication(self.publication,raw,ordinal)
        recorder = self.opened()
        self.assertEqual(5,recorder.poll()['admitted'])
        return recorder

    def health(self, ordinal):
        raw = export_envelope_v2('PROVIDER_HEALTH',health_payload(
            health_id=identity('PROVIDER_HEALTH_EVENT_ID',f'N005-{ordinal}')),
            stream_id=f'N005-health-{ordinal}',event_id=f'N005-health-{ordinal}')
        return publication(self.publication,raw,ordinal)

    @staticmethod
    def guards(recorder):
        return (recorder.recorder._views.changes,recorder._support.ledger_changes,
                recorder._support.producer_changes,recorder.reader._cursor_changes)

    def assert_old_bytes(self, before):
        after = immutable(self.science)
        self.assertTrue(all(after.get(path)==digest for path,digest in before.items()))

    def test_exact_minimal_scopes_keep_default_buffer_and_root_pins(self):
        recorder = self.started()
        expected = [(self.science/'custody/sessions',True),(self.science/'arrivals/ledger',False),
                    (self.publication,False),(self.science/'reader/cursors',False)]
        for guard,(root,recursive) in zip(self.guards(recorder),expected):
            self.assertEqual(root,guard.root)
            self.assertEqual(recursive,guard.recursive)
            self.assertEqual(65536,ctypes.sizeof(guard.buffer))
            with self.assertRaises(OSError):
                root.rename(root.with_name(root.name+'-redirected'))

    def test_one_large_publication_120_observations_no_history_scan(self):
        recorder = self.started()
        rows = [observation(identity('OBSERVATION_ID',f'N005-large-{i}'),ordinal=i,symbol=f'SYN{i}')
                for i in range(120)]
        raw = export_envelope_v2('DISCOVERY_CYCLE',discovery_payload(rows),
            stream_id='N005-discovery',event_id='N005-large')
        publication(self.publication,raw,2)
        views = recorder.recorder._views
        baseline = views.counters['namespace_audits']
        with ExitStack() as stack:
            for target,name in [(views,'_inventory'),(views.reads,'audit_known'),
                    (recorder._ledger_reads,'audit_known'),(recorder.recorder,'verify'),
                    (recorder,'records'),(recorder._support,'_baseline_producer'),
                    (StrategyScienceSourceReaderV2,'_load_state')]:
                stack.enter_context(patch.object(target,name,side_effect=AssertionError('Normal history scan: '+name)))
            result = recorder.poll(max_items=1)
            self.assertEqual(1,result['admitted'])
            self.assertEqual(0,recorder.poll()['admitted'])
        self.assertEqual(120,result['coverage']['canonical']['candidate_observations'])
        self.assertEqual(baseline,views.counters['namespace_audits'])
        self.assertEqual(result['coverage']['canonical'],recorder.coverage()['canonical'])

    def test_1_10_100_sequential_publications_and_100_publication_burst(self):
        recorder = self.started()
        before = recorder.recorder._views.counters['namespace_audits']
        for ordinal in range(2,102):
            self.health(ordinal)
            result = recorder.poll(max_items=1)
            self.assertEqual(1,result['admitted'])
            if ordinal-1 in (1,10,100):
                self.assertEqual(ordinal-1,result['coverage']['family_counts']['provider-health-event'])
        for ordinal in range(102,202):
            self.health(ordinal)
        result = recorder.poll(max_items=100)
        self.assertEqual(100,result['admitted'])
        self.assertEqual(200,result['coverage']['family_counts']['provider-health-event'])
        self.assertEqual(0,recorder.poll()['admitted'])
        self.assertEqual(before,recorder.recorder._views.counters['namespace_audits'])
        self.assertEqual(result['coverage']['canonical'],recorder.coverage()['canonical'])

    def test_excluded_staging_and_quarantine_storms_do_not_overflow_custody(self):
        recorder = self.started()
        before = immutable(self.science)
        for path in (self.science/'custody/.partial',self.science/'custody/.quarantine',
                     self.science/'arrivals/.partial',self.science/'reader/cursors/.partial'):
            name_storm(path)
        self.assertEqual(0,recorder.poll()['admitted'])
        self.assertTrue(all(not guard.failed for guard in self.guards(recorder)))
        self.assert_old_bytes(before)

    def test_real_custody_overflow_after_commit_is_not_semantic_rejection_and_reopens(self):
        recorder = self.started()
        publication(self.publication,core_fixtures()[1],2)
        baseline = immutable(self.science)
        actual = recorder.reader._verify_custody_commit
        def interrupted(*args):
            name_storm(recorder.recorder._views.changes.root)
            return actual(*args)
        with patch.object(recorder.reader,'_verify_custody_commit',side_effect=interrupted):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll(max_items=1)
        self.assertTrue(recorder.recorder._views.changes.failed)
        self.assertFalse(recorder._rejected)
        with self.assertRaisesRegex(ContinuousRecorderError,'close/reopen'):
            recorder.poll()
        committed = immutable(self.science)
        recorder.close()
        reopened = self.opened()
        result = reopened.poll()
        self.assertEqual(2,result['coverage']['admitted_arrival_count'])
        self.assertEqual(2,result['coverage']['canonical']['candidate_observations'])
        self.assertEqual(0,result['coverage']['pending_count'])
        self.assertEqual(0,result['coverage']['rejected_count'])
        self.assertEqual(0,reopened.poll()['admitted'])
        self.assert_old_bytes(baseline)
        self.assert_old_bytes(committed)
        self.assertEqual(result['coverage']['canonical'],reopened.coverage()['canonical'])

    def test_real_ledger_overflow_raw_ahead_of_memory_recovers_once(self):
        recorder = self.started()
        self.health(2)
        original = recorder._support.ledger_published
        def interrupted(path):
            name_storm(recorder._support.ledger_changes.root)
            return original(path)
        with patch.object(recorder._support,'ledger_published',side_effect=interrupted):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll(max_items=1)
        self.assertTrue(recorder._support.ledger_changes.failed)
        self.assertFalse(recorder._rejected)
        before = immutable(self.science)
        recorder.close()
        reopened = self.opened()
        result = reopened.poll()
        self.assertEqual(2,result['coverage']['admitted_arrival_count'])
        self.assertEqual(0,reopened.poll()['admitted'])
        self.assertEqual(1,result['coverage']['family_counts']['provider-health-event'])
        self.assert_old_bytes(before)

    def test_real_cursor_overflow_committed_cursor_recovers_admission_marker_once(self):
        recorder = self.started()
        self.health(2)
        actual = recorder.reader._cursor_committed
        def interrupted(*args):
            name_storm(recorder.reader._cursor_changes.root)
            return actual(*args)
        with patch.object(recorder.reader,'_cursor_committed',side_effect=interrupted):
            with self.assertRaises(ContinuousRecorderError):
                recorder.poll(max_items=1)
        self.assertTrue(recorder.reader._cursor_changes.failed)
        self.assertFalse(recorder._rejected)
        before = immutable(self.science)
        recorder.close()
        reopened = self.opened()
        self.assertEqual(0,reopened.poll()['admitted'])
        result = reopened.coverage()
        self.assertEqual(2,result['admitted_arrival_count'])
        self.assertEqual(1,result['family_counts']['provider-health-event'])
        self.assert_old_bytes(before)

    def test_real_producer_overflow_at_entry_no_healthy_reuse_and_cold_recovery(self):
        recorder = self.started()
        before = immutable(self.science)
        name_storm(self.publication)
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()
        self.assertTrue(recorder._support.producer_changes.failed)
        with self.assertRaisesRegex(ContinuousRecorderError,'close/reopen'):
            recorder.poll()
        recorder.close()
        self.health(2)  # Authoritative input arrived while Science was closed.
        reopened = self.opened()
        self.assertEqual(1,reopened.poll()['admitted'])
        self.assertEqual(0,reopened.poll()['admitted'])
        self.assert_old_bytes(before)

    def test_transient_unknown_names_during_audit_entry_and_exit_fail(self):
        for boundary in (1,2):
            with self.subTest(boundary=boundary):
                recorder = self.started() if boundary==1 else self.opened()
                actual = recorder.recorder._views._inventory
                calls = 0
                def interrupted():
                    nonlocal calls
                    calls += 1
                    value = actual()
                    if calls == boundary:
                        path = recorder.recorder._views.changes.root/'unowned-transient.json'
                        path.write_bytes(b'{}')
                        path.unlink()
                    return value
                with patch.object(recorder.recorder._views,'_inventory',side_effect=interrupted):
                    with self.assertRaises(ContinuousRecorderError):
                        recorder.coverage()
                self.assertTrue(recorder.recorder._views.failed)
                with self.assertRaises(ContinuousRecorderError):
                    recorder.poll()
                recorder.close()

    def test_real_overflow_during_full_audit_requires_new_generation(self):
        recorder = self.started()
        actual = recorder.recorder._views._inventory
        def interrupted():
            value = actual()
            name_storm(recorder.recorder._views.changes.root)
            return value
        with patch.object(recorder.recorder._views,'_inventory',side_effect=interrupted):
            with self.assertRaises(ContinuousRecorderError):
                recorder.coverage()
        self.assertTrue(recorder.recorder._views.changes.failed)
        recorder.close()
        reopened = self.opened()
        self.assertEqual(1,reopened.coverage()['admitted_arrival_count'])

    def test_transient_custody_change_inside_cold_start_audit_fails_and_closes(self):
        publication(self.publication,core_fixtures()[0],1)
        prior_unretired = len(_unretired_requests)
        actual = ReusableViews._inventory
        seen = []
        def interrupted(views):
            value = actual(views)
            if not seen:
                seen.append(views)
                path = views.changes.root/'unowned-startup-transient.json'
                path.write_bytes(b'{}')
                path.unlink()
            return value
        with patch.object(ReusableViews,'_inventory',new=interrupted):
            with self.assertRaisesRegex(RecorderRecoveryError,'outside local committed deltas'):
                self.opened()
        self.assertEqual(1,len(seen))
        self.assertTrue(seen[0].failed)
        self.assertTrue(seen[0].changes.closed)
        self.assertIsNone(seen[0].changes.handle)
        self.assertIsNone(seen[0].changes.event)
        self.assertEqual(prior_unretired,len(_unretired_requests))
        reopened = self.opened()
        self.assertEqual(1,reopened.poll()['admitted'])
        self.assertEqual(0,reopened.poll()['admitted'])

    def test_publication_during_restart_after_producer_baseline_is_admitted_once(self):
        recorder = self.started()
        original = immutable(self.science)
        recorder.close()
        actual = ContinuousIncremental._baseline_producer
        seen = []
        def interrupted(support):
            actual(support)
            if not seen:
                seen.append(support)
                self.health(2)
        with patch.object(ContinuousIncremental,'_baseline_producer',new=interrupted):
            reopened = self.opened()
        result = reopened.poll()
        self.assertEqual(1,result['admitted'])
        self.assertEqual(2,result['coverage']['admitted_arrival_count'])
        self.assertEqual(1,result['coverage']['family_counts']['provider-health-event'])
        self.assertEqual(0,reopened.poll()['admitted'])
        self.assert_old_bytes(original)
        self.assertEqual(result['coverage']['canonical'],reopened.coverage()['canonical'])

    def test_unknown_flat_ledger_and_cursor_directory_not_silently_ignored(self):
        for location in ('arrivals/ledger','reader/cursors'):
            with self.subTest(location=location):
                recorder = self.started() if location.startswith('arrivals') else self.opened()
                path = self.science/location/'unowned-directory'
                path.mkdir()
                with self.assertRaises((ContinuousRecorderError,SourceReaderCursorError)):
                    recorder.poll()
                recorder.close()
                path.rmdir()  # Test-owned empty adversarial directory only.

    def test_modification_append_rename_delete_replace_and_hardlink_rejected(self):
        for mutation in ('write','append','rename','delete','replace','hardlink'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix='N005-matrix-') as temp:
                original_root,original_science,original_publication = self.root,self.science,self.publication
                self.root = Path(temp)
                self.science = self.root/'science'
                self.publication = self.root/'producer/published'
                recorder = self.populated()
                path = next(self.science.rglob('*.payload.json'))
                raw = path.read_bytes()
                try:
                    if mutation=='write':
                        path.write_bytes(raw+b' ')
                    elif mutation=='append':
                        with path.open('ab') as stream:
                            stream.write(b' ')
                    elif mutation=='rename':
                        path.rename(path.with_name('renamed.payload.json'))
                    elif mutation=='delete':
                        path.unlink()
                    elif mutation=='replace':
                        replacement = path.with_name('replacement')
                        replacement.write_bytes(raw)
                        os.replace(replacement,path)
                    else:
                        os.link(path,path.with_name('external-alias.payload.json'))
                    # Missing-path identity is an explicit OS failure, not a
                    # healthy return; the existing API does not wrap it.
                    with self.assertRaises((ContinuousRecorderError,FileNotFoundError)):
                        recorder.poll()
                except PermissionError:
                    # An OS denied mutation is stronger prevention, not an
                    # observed-notification claim. The retained bytes must match.
                    self.assertEqual(raw,path.read_bytes())
                finally:
                    recorder.close()
                    self.root,self.science,self.publication = original_root,original_science,original_publication

    def test_external_alias_metadata_audit_and_content_write_coherence_distinct(self):
        recorder = self.populated()
        path = next(self.science.rglob('*.payload.json'))
        alias = self.root/'outside-watch-alias'
        os.link(path,alias)
        with self.assertRaises(ContinuousRecorderError):
            recorder.coverage()
        alias.write_bytes(b'changed through external alias')
        with self.assertRaises(ContinuousRecorderError):
            recorder.poll()

    def test_producer_changed_across_restart_preserves_raw_and_freezes(self):
        recorder = self.started()
        original = immutable(self.science)
        recorder.close()
        path = next(self.publication.iterdir())
        path.write_bytes(path.read_bytes()+b' ')
        # The unchanged base Reader validates old input during construction,
        # before a reopened owner can poll or claim a healthy generation.
        with self.assertRaises((ContinuousRecorderError,SourceReaderPublicationError)):
            reopened = self.opened()
            reopened.poll()
        self.assert_old_bytes(original)

    def test_namespace_classification_is_exact_and_semantic_errors_not_relaxed(self):
        signal = NamespaceRecoveryRequired('lost native continuity')
        wrapper = RuntimeError('wrapped')
        wrapper.__cause__ = signal
        for value in (signal,wrapper):
            self.assertTrue(ContinuousScienceRecorder._storage_interruption(value))
        for value in (VerifiedReadError('raw changed'),ValueError('invalid semantic source'),
                      ContinuousRecorderError('semantic rejected')):
            self.assertFalse(ContinuousScienceRecorder._storage_interruption(value))

    def test_rapid_events_during_close_retire_requests_and_repeated_restart(self):
        before = len(_unretired_requests)
        for index in range(10):
            recorder = self.started() if index==0 else self.opened()
            guards = self.guards(recorder)
            target = guards[2]
            cancel = target.kernel.CancelIoEx
            def race(*args):
                path = self.publication/'during-cancel'
                path.write_bytes(b'transient')
                path.unlink()
                return cancel(*args)
            with patch.object(target.kernel,'CancelIoEx',side_effect=race):
                recorder.close()
            for guard in guards:
                self.assertTrue(guard.closed)
                self.assertIsNone(guard.handle)
                self.assertIsNone(guard.event)
            self.assertEqual(before,len(_unretired_requests))


if __name__ == '__main__':
    unittest.main()
