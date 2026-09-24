"""Real recorder/notification integration over a structural test mailbox.

The filesystem fixture's owner/descriptor labels are simulated, NOT Windows
ACL proof. Native ownership/denial is a separate required qualification gate.
All scientific payloads are the existing synthetic canonical test fixtures.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePath
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from momentum_hunter.science_custody_commit import (
    CustodyCommitError, CustodyCommitPending, CustodyObjectEvidence,
    ScienceCustodyFinalizer,
)
from momentum_hunter.science_custody_mailbox import (
    ScienceCustodyMailboxClient, ScienceCustodyMailboxWriter,
)
from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet
from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder
from momentum_hunter.strategy_science_recorder.custody import RecorderRecoveryError, StrategyScienceRecorder
from momentum_hunter.strategy_science_source_reader import SourceReaderError, StrategyScienceSourceReaderV2
from tests.test_strategy_science_continuous_recorder import core_fixtures, publication, TickingClock
from tests.test_strategy_science_recorder_contract import (
    SOURCE_ROOT_IDENTITY, SESSION_ID, outcome_attachment, source_final_envelope, stored_records,
)
from tests.test_strategy_science_recorder_eligibility_authority import (
    start_envelope_v2, export_envelope_v2, v2_outcome_payload,
)


class FilesystemProtocolFixture:
    """Test-only structural backend; never imported by production modules."""
    policy_sha256 = 'a' * 64
    source_root_identity = SOURCE_ROOT_IDENTITY
    max_artifact_bytes = 64 * 1024 * 1024
    max_request_bytes = 64 * 1024
    role = 'science'

    def __init__(self, root, *, start_writer=True):
        self.base = root
        self.science = root / 'science'
        self.derived_root = root / 'derived'
        self.roots = {name: root / name for name in ('staging', 'requests', 'claims', 'receipts')}
        self.roots.update(arrivals=self.science / 'arrivals', custody=self.science / 'custody',
                          cursors=self.science / 'reader' / 'cursors')
        for path in (*self.roots.values(), self.derived_root,
                     self.science / 'arrivals' / 'ledger', self.science / 'custody' / 'sessions'):
            path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.history_visits = self.trusted_creates = self.polls = 0
        self.created_paths = []
        self.errors = []
        self.stop = threading.Event()
        self.finalizer = ScienceCustodyFinalizer(self)
        self.worker = ScienceCustodyMailboxWriter(self.finalizer, mailbox_backend=self)
        self.thread = threading.Thread(target=self._run, daemon=True)
        if start_writer:
            self.thread.start()

    def _run(self):
        while not self.stop.wait(0.001):
            try:
                self.polls += 1
                self.worker.poll_once()
            except CustodyCommitPending:
                pass
            except BaseException as exc:
                self.errors.append(exc)
                return

    @contextmanager
    def transaction(self):
        with self.lock:
            yield

    def namespace_root(self, alias):
        return self.roots[alias]

    @staticmethod
    def evidence(path, maximum):
        stat = path.stat()
        raw = path.read_bytes()
        if len(raw) > maximum or stat.st_nlink != 1:
            raise CustodyCommitError('Structural fixture bound/alias failure.')
        return CustodyObjectEvidence(raw, (stat.st_dev & 0xffffffff,
                                           stat.st_ino >> 32, stat.st_ino & 0xffffffff),
                                     'TEST_ONLY_SIMULATED_OWNER_NOT_NATIVE_PROOF', 'b' * 64)

    def validate_readonly_roots(self):
        return {name: SimpleNamespace(root=path,
                    file_identity=(path.stat().st_dev & 0xffffffff,
                                   path.stat().st_ino >> 32, path.stat().st_ino & 0xffffffff),
                    owner_sid='TEST_ONLY_SIMULATED_OWNER_NOT_NATIVE_PROOF', descriptor_sha256='b' * 64)
                for name, path in self.roots.items()}

    def read_staged(self, name, *, maximum):
        return self.evidence(self.roots['staging'] / name, maximum)

    def read_request(self, name, *, maximum):
        return self.evidence(self.roots['requests'] / name, maximum)

    def read_trusted(self, namespace, relative, *, maximum):
        path = self.roots[namespace] / relative
        try:
            return self.evidence(path, maximum)
        except FileNotFoundError:
            return None

    def create_trusted(self, namespace, relative, raw):
        with self.lock:
            path = self.roots[namespace] / relative
            if path.exists():
                existing = self.evidence(path, self.max_artifact_bytes)
                if existing.raw != raw:
                    raise CustodyCommitError('Structural write-once conflict.')
                self.ensure_durable(namespace, relative, existing)
                return False, existing
            path.parent.mkdir(parents=True, exist_ok=True)
            self._install(path, raw)
            self.trusted_creates += 1
            self.created_paths.append((namespace, relative))
            evidence = self.evidence(path, self.max_artifact_bytes)
            self.ensure_durable(namespace, relative, evidence)
            return True, evidence

    def ensure_durable(self, namespace, relative, expected):
        path = self.roots[namespace] / relative
        if self.evidence(path, self.max_artifact_bytes) != expected:
            raise CustodyCommitError('Structural durability target changed.')
        with path.open('r+b') as stream:
            os.fsync(stream.fileno())
        if self.evidence(path, self.max_artifact_bytes) != expected:
            raise CustodyCommitError('Structural durability target changed across flush.')

    def publish_completion(self, relative, raw):
        with self.lock:
            path = self.roots['receipts'] / relative
            if path.exists():
                existing = self.evidence(path, self.max_request_bytes)
                if existing.raw != raw:
                    raise CustodyCommitError('Structural completion conflict.')
                return False, existing
            path.parent.mkdir(parents=True, exist_ok=True)
            self._install(path, raw)
            return True, self.evidence(path, self.max_request_bytes)

    def _install(self, path, raw):
        temporary = self.derived_root / (uuid.uuid4().hex + '.test-private')
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()

    def create_transport(self, namespace, name, raw):
        with self.lock:
            path = self.roots[namespace] / name
            self._install(path, raw)
            return self.evidence(path, self.max_artifact_bytes)

    def delete_transport(self, namespace, name, *, expected_identity, expected_sha256):
        with self.lock:
            path = self.roots[namespace] / name
            if not path.exists():
                return
            actual = self.evidence(path, self.max_artifact_bytes)
            if actual.file_identity != tuple(expected_identity) or hashlib.sha256(actual.raw).hexdigest() != expected_sha256:
                raise CustodyCommitError('Structural cleanup identity mismatch.')
            path.unlink()

    def bounded_names(self, namespace, limit):
        with self.lock:
            result = []
            for path in self.roots[namespace].iterdir():
                result.append(path.name)
                if len(result) >= limit:
                    break
            return tuple(result)

    def iter_trusted(self, alias, relative='', *, suffix):
        path = self.roots[alias] / relative
        result = []
        if path.exists():
            for item in path.rglob('*'):
                self.history_visits += 1
                if item.is_file() and item.name.endswith(suffix):
                    self.evidence(item, self.max_artifact_bytes)
                    result.append(item)
        return tuple(sorted(result))

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(5)
        if self.thread.is_alive():
            raise AssertionError('Structural test worker did not stop.')


class PublicationReadbackReuseTests(unittest.TestCase):
    def test_confirmed_bytes_are_compared_locally_before_fresh_ack(self):
        for mutation in (None, 'after_confirm', 'before_ack'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / 'record.json'
                raw = b'committed'
                calls = []

                def create(_relative, value):
                    calls.append('create')
                    path.write_bytes(value)
                    return True

                def confirm(_relative):
                    calls.append('confirm')
                    return path.read_bytes()

                def published(_relative):
                    calls.append('published')
                    if mutation == 'after_confirm':
                        path.write_bytes(b'substituted')

                def acknowledge(_relative, value):
                    calls.append('ack')
                    if mutation == 'before_ack':
                        path.write_bytes(b'substituted')
                    if path.read_bytes() != value:
                        raise RecorderRecoveryError('Fresh acknowledgement rejected substitution.')

                recorder = object.__new__(StrategyScienceRecorder)
                recorder._storage = SimpleNamespace(root=root, atomic_create=create,
                    read_committed=confirm, publication_verified=acknowledge)
                recorder._views = SimpleNamespace(depth=0, published=published)
                recorder._custody_storage_set = object()
                if mutation is None:
                    self.assertTrue(recorder._atomic_create(PurePath('record.json'), raw))
                    self.assertEqual(calls, ['create', 'confirm', 'published', 'ack'])
                else:
                    with self.assertRaises(RecorderRecoveryError):
                        recorder._atomic_create(PurePath('record.json'), raw)
                    self.assertEqual(calls, ['create', 'confirm', 'published'] +
                                     (['ack'] if mutation == 'before_ack' else []))


@unittest.skipUnless(os.name == 'nt', 'Science005 notification compatibility requires Windows')
class SealedRecorderIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='S007-integration-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.publication = self.root / 'producer' / 'published'
        self.publication.mkdir(parents=True)
        self.backend = FilesystemProtocolFixture(self.root)
        self.addCleanup(self.backend.close)
        self.clock = TickingClock()

    def storage_set(self, *, readiness_trace=None):
        client = ScienceCustodyMailboxClient(policy_sha256=self.backend.policy_sha256,
                    source_root_identity=SOURCE_ROOT_IDENTITY, mailbox_backend=self.backend)
        return ScienceCustodyStorageSet(client, timeout_seconds=3, recovery_clock=self.clock,
                                       readiness_trace=readiness_trace)

    def test_readiness_trace_marks_pending_read_without_changing_result(self):
        events = []
        storage = self.storage_set(readiness_trace=lambda event, **detail: events.append((event, detail)))
        entered = threading.Event()
        release = threading.Event()
        outcome = []

        def held_read(alias, relative):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Deterministic read barrier timed out.')
            return SimpleNamespace(raw=b'confirmed')

        def reader():
            try:
                outcome.append(storage.read_committed('arrivals', 'ledger/bound.json'))
            except Exception as exc:
                outcome.append(exc)

        with patch.object(storage.client, 'read_confirmed', side_effect=held_read):
            thread = threading.Thread(target=reader)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual([name for name, _ in events], ['SCIENCE_CUSTODY_READ_CONFIRM_ENTER'])
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [b'confirmed'])
        self.assertEqual([name for name, _ in events],
                         ['SCIENCE_CUSTODY_READ_CONFIRM_ENTER', 'SCIENCE_CUSTODY_READ_CONFIRM_EXIT'])
        self.assertEqual(events[0][1], {'alias': 'arrivals', 'relative_path': 'ledger/bound.json'})

    def test_readiness_trace_failure_does_not_change_custody_result(self):
        def failed_trace(event, **detail):
            raise RuntimeError('qualification trace unavailable')

        storage = self.storage_set(readiness_trace=failed_trace)
        raw = b'{"profile":"SCIENCE_CONTINUOUS_RECEIPT_LEDGER_V1","sequence":2}\n'
        relative = 'ledger/' + '00000000000000000002-' + hashlib.sha256(raw).hexdigest() + '.event.json'
        storage.publish('arrivals', relative, raw)
        self.assertEqual(storage.read_committed('arrivals', relative), raw)
        storage.publication_verified('arrivals', relative, raw)
        self.assertFalse(list(self.backend.roots['requests'].iterdir()))

    def test_readiness_trace_preserves_publish_read_ack_order(self):
        events = []
        storage = self.storage_set(readiness_trace=lambda event, **detail: events.append(event))
        raw = b'{"profile":"SCIENCE_CONTINUOUS_RECEIPT_LEDGER_V1","sequence":3}\n'
        relative = 'ledger/' + '00000000000000000003-' + hashlib.sha256(raw).hexdigest() + '.event.json'
        storage.publish('arrivals', relative, raw)
        self.assertEqual(storage.read_committed('arrivals', relative), raw)
        storage.publication_verified('arrivals', relative, raw)
        self.assertEqual(events, [
            'SCIENCE_CUSTODY_PUBLISH_ENTER', 'SCIENCE_CUSTODY_AWAIT_ENTER',
            'SCIENCE_CUSTODY_AWAIT_EXIT', 'SCIENCE_CUSTODY_PUBLISH_EXIT',
            'SCIENCE_CUSTODY_READ_CONFIRM_ENTER', 'SCIENCE_CUSTODY_READ_CONFIRM_EXIT',
            'SCIENCE_CUSTODY_ACK_ENTER', 'SCIENCE_CUSTODY_ACK_EXIT',
        ])

    def opened(self, storage_set=None):
        instance = ContinuousScienceRecorder(self.publication, self.backend.science,
                    source_root_identity=SOURCE_ROOT_IDENTITY, writer_instance_id='synthetic-007',
                    clock=self.clock, custody_storage_set=storage_set or self.storage_set())
        self.addCleanup(instance.close)
        return instance

    def test_real_ingress_seals_arrivals_custody_and_cursors_with_no_writer_in_science(self):
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.publication, raw, ordinal)
        storage_set = self.storage_set()
        with (patch('momentum_hunter.strategy_science_continuous_recorder.WriterPhysicalStorage',
                   side_effect=AssertionError('Science attempted direct Writer construction')),
             patch('momentum_hunter.strategy_science_recorder.custody.WriterPhysicalStorage',
                   side_effect=AssertionError('Science attempted direct custody Writer'))):
            recorder = self.opened(storage_set)
            result = recorder.poll()
        self.assertEqual(result['admitted'], 5)
        self.assertFalse(self.backend.errors, self.backend.errors)
        aliases = {alias for alias, _ in self.backend.created_paths}
        self.assertTrue({'arrivals', 'custody', 'cursors', 'claims', 'receipts'} <= aliases)
        self.assertFalse(list(self.backend.roots['staging'].iterdir()))
        self.assertFalse(list(self.backend.roots['requests'].iterdir()))
        self.assertFalse((recorder.reader.cursor_root / '.partial').exists())
        self.assertTrue((self.backend.derived_root / '.reader.lock').exists())
        self.assertEqual(0, recorder.poll()['admitted'])

    def test_reader_cannot_fall_back_to_science_owned_cursor_with_sealed_recorder(self):
        recorder = self.opened()
        with self.assertRaisesRegex(SourceReaderError, 'sealed cursor'):
            StrategyScienceSourceReaderV2(self.publication, self.root / 'alternate-reader',
                                         recorder=recorder.recorder)

    def test_next_commit_blocked_until_exact_owner_callback(self):
        storage = self.storage_set()
        raw = b'{"profile":"SCIENCE_CONTINUOUS_RECEIPT_LEDGER_V1","sequence":1}\n'
        relative = 'ledger/' + '00000000000000000001-' + hashlib.sha256(raw).hexdigest() + '.event.json'
        storage.publish('arrivals', relative, raw)
        with self.assertRaises(CustodyCommitPending):
            storage.publish('arrivals', relative, raw)
        with self.assertRaises(CustodyCommitError):
            storage.publication_verified('arrivals', relative, b'changed')
        self.assertTrue(list(self.backend.roots['requests'].iterdir()))
        storage.publication_verified('arrivals', relative, raw)
        self.assertFalse(list(self.backend.roots['requests'].iterdir()))

    def test_readback_failure_keeps_slot_and_recovery_does_not_rewrite_raw(self):
        publication(self.publication, core_fixtures()[0], 1)
        recorder = self.opened()
        publication(self.publication, core_fixtures()[1], 2)
        with patch.object(recorder.recorder._storage, 'publication_verified',
                          side_effect=OSError('synthetic after final, before local acknowledgement')):
            with self.assertRaises(Exception):
                recorder.poll()
        before = {p: p.read_bytes() for p in self.backend.science.rglob('*') if p.is_file()}
        self.assertTrue(list(self.backend.roots['requests'].iterdir()))
        recorder.close()
        reopened = self.opened()
        reopened.poll()
        self.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))
        self.assertFalse(self.backend.errors, self.backend.errors)

    def test_outcomes_remain_separate_and_final_manifest_checksum_are_sealed(self):
        for ordinal, raw in enumerate(core_fixtures(), 1):
            publication(self.publication, raw, ordinal)
        recorder = self.opened()
        recorder.poll()
        decisions = {path: raw for path, _, raw in stored_records(
            recorder.custody_root, 'decision-event')}
        attachment = outcome_attachment(v2_outcome_payload(recorder.custody_root))
        self.assertEqual('ACCEPTED', recorder.append_outcome(attachment)['status'])
        self.assertEqual('IDEMPOTENT_ACK', recorder.append_outcome(attachment)['status'])
        self.assertEqual(decisions, {path: path.read_bytes() for path in decisions})
        legacy = json.loads(source_final_envelope(recorder.recorder, start_envelope_v2()))
        final = export_envelope_v2('SESSION_MANIFEST', legacy['payload'],
                    stream_id='session-stream', event_id='session-final', sequence=2,
                    previous=hashlib.sha256(start_envelope_v2()).hexdigest())
        publication(self.publication, final, 6)
        recorder.poll()
        result = recorder.recorder.finalize(SESSION_ID)
        self.assertEqual('FINALIZED', result.status)
        self.assertTrue(recorder.recorder.verify(SESSION_ID).all_hashes_valid)
        self.assertEqual('IDEMPOTENT_ACK', recorder.recorder.finalize(SESSION_ID).status)
        custody_paths = [path for alias, path in self.backend.created_paths if alias == 'custody']
        self.assertEqual(1, sum(path.endswith('.final.json') for path in custody_paths))
        self.assertEqual(1, sum(path.endswith('.sha256') for path in custody_paths))
        self.assertFalse(self.backend.errors, self.backend.errors)

    def test_unsubmitted_stage_recovery_is_explicit_new_metadata_not_observation(self):
        storage = self.storage_set()
        raw = b'{"sequence":1}\n'
        path = 'ledger/00000000000000000001-' + hashlib.sha256(raw).hexdigest() + '.event.json'
        with self.assertRaises(CustodyCommitPending):
            storage.publish('arrivals', path, raw, crash_after_temp=True)
        self.assertEqual(1, len(list(self.backend.roots['staging'].iterdir())))
        recovered = self.storage_set()
        self.assertFalse(list(self.backend.roots['staging'].iterdir()))
        self.assertFalse(list((self.backend.roots['arrivals'] / 'ledger').iterdir()))
        receipts = list(self.backend.roots['custody'].glob('quarantine-receipts/*.json'))
        self.assertEqual(1, len(receipts))
        value = json.loads(receipts[0].read_bytes())
        self.assertEqual('ABANDONED_STAGING_NOT_ADMITTED', value['classification'])
        self.assertEqual('NONE', value['source_admission'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), value['partial_before']['sha256'])
        self.assertFalse(self.backend.errors, self.backend.errors)
