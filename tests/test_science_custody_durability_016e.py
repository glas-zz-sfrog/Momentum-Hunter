"""Durability ordering controls; native doubles do not prove OS isolation."""
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import windows_science_custody as native_module
from momentum_hunter.science_custody_commit import (
    CustodyCommitError, CustodyCommitIntegrityError, CustodyCommitPending,
    CustodyCommitReceipt, CustodyCommitResult, ScienceCustodyFinalizer,
    claim_path, completion_path, receipt_path, sha256,
)
from momentum_hunter.science_custody_mailbox import (
    CustodyPendingRequest, ScienceCustodyMailboxClient,
)
from momentum_hunter.science_custody_readonly import ScienceCustodyStorageSet
from tests.test_science_custody_commit_007 import MemoryBackend, arrival, request_for
from tests.test_science_custody_recorder_007 import FilesystemProtocolFixture
from tests.test_science_custody_recorder_007 import core_fixtures, publication, TickingClock
from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder
from tests.test_science_custody_windows_007 import NativeDouble, policy


class OrderedNative(NativeDouble):
    """Deterministic visible-object API outcomes, not a power-loss model."""
    def __init__(self, bound_policy):
        super().__init__(bound_policy)
        self.flushes = []
        self.fail_receipt_flush = False
        self.fail_suffix = None
        self.k.FlushFileBuffers = self.flush

    def flush(self, value):
        obj = self.handles[value].obj
        failed = ((self.fail_receipt_flush and obj.path.name.endswith('.commit.json'))
                  or (self.fail_suffix is not None and str(obj.path).endswith(self.fail_suffix)))
        self.flushes.append((obj.identity, str(obj.path), not failed, self.role))
        return 0 if failed else 1


class NativeDurabilityOrderingTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy(max_request_bytes=4096)
        self.native = OrderedNative(self.policy)
        self.backends = []
        self.writer = self.backend('writer')
        fixture = MemoryBackend()
        original = request_for(fixture)
        self.raw = fixture.objects['staging', original.staging_name].raw
        self.request = replace(original, policy_sha256=self.policy.policy_sha256,
            identity=replace(original.identity, source_root_identity=self.policy.source_root_identity))
        self.stage = self.native.add(self.writer.namespace_root('staging') / self.request.staging_name,
                                     kind='transport', raw=self.raw)
        self.slot = self.native.add(self.writer.namespace_root('requests') / 'request.json',
                                    kind='transport', raw=self.request.to_bytes())
        self.pending = CustodyPendingRequest(self.request, self.slot.identity, self.stage.identity)

    def tearDown(self):
        for backend in reversed(self.backends):
            self.native.role = backend.role
            backend.close()

    def backend(self, role):
        self.native.role = role
        with patch.object(native_module, '_Native', return_value=self.native):
            backend = native_module.WindowsScienceCustodyBackend(self.policy, role=role)
        backend.bounded_names = lambda namespace, limit: tuple(sorted(
            obj.path.name for obj in self.native.objects.values()
            if obj.path.parent == backend.namespace_root(namespace)))[:limit]
        self.backends.append(backend)
        return backend

    def client(self, backend):
        return ScienceCustodyMailboxClient(policy_sha256=self.policy.policy_sha256,
            source_root_identity=self.policy.source_root_identity, mailbox_backend=backend)

    def visible_result(self):
        key = native_module._path_key(self.writer.namespace_root('receipts') /
                                      receipt_path(self.request.identity.digest()))
        return CustodyCommitResult(CustodyCommitReceipt.from_bytes(self.native.objects[key].raw), False, False)

    def assert_pending_without_cleanup(self, client):
        before = len(self.native.flushes)
        self.assertIsNone(client.reconcile(self.pending))
        with self.assertRaises(CustodyCommitIntegrityError):
            client.acknowledge(self.pending, self.visible_result())
        self.assertFalse(self.stage.deleted)
        self.assertFalse(self.slot.deleted)
        self.assertEqual(before, len(self.native.flushes))

    def test_failed_receipt_flush_original_readonly_client_cannot_acknowledge(self):
        reader = self.backend('science')
        client = self.client(reader)
        self.native.role = 'writer'
        self.native.fail_receipt_flush = True
        with self.assertRaises(OSError):
            ScienceCustodyFinalizer(self.writer).finalize(self.request)
        self.native.role = 'science'
        self.assert_pending_without_cleanup(client)

    def test_failed_receipt_flush_fresh_readonly_client_cannot_acknowledge(self):
        self.native.fail_receipt_flush = True
        with self.assertRaises(OSError):
            ScienceCustodyFinalizer(self.writer).finalize(self.request)
        self.writer.close()
        reader = self.backend('science')
        self.assert_pending_without_cleanup(self.client(reader))

    def test_normal_commit_and_readonly_cleanup(self):
        result = ScienceCustodyFinalizer(self.writer).finalize(self.request)
        reader = self.backend('science')
        client = self.client(reader)
        exact = client.reconcile(self.pending)
        self.assertEqual(result.receipt, exact.receipt)
        before = len(self.native.flushes)
        client.acknowledge(self.pending, exact)
        self.assertTrue(self.stage.deleted)
        self.assertTrue(self.slot.deleted)
        self.assertEqual(before, len(self.native.flushes))

    def object_for(self, namespace, relative):
        return self.native.objects[native_module._path_key(self.writer.namespace_root(namespace) / relative)]

    def test_writer_restart_reflushes_all_exact_objects_before_ack(self):
        self.native.fail_receipt_flush = True
        with self.assertRaises(OSError):
            ScienceCustodyFinalizer(self.writer).finalize(self.request)
        original = self.visible_result().receipt
        self.writer.close()
        self.native.fail_receipt_flush = False
        writer = self.backend('writer')
        before = len(self.native.flushes)
        result = ScienceCustodyFinalizer(writer).finalize(self.request)
        self.assertEqual(original, result.receipt)
        flushed = {identity for identity, _, ok, _ in self.native.flushes[before:] if ok}
        for namespace, relative in [('claims', claim_path(self.request.identity.digest())),
                                    ('receipts', receipt_path(self.request.identity.digest())),
                                    ('arrivals', self.request.final_relative_path)]:
            self.assertIn(self.object_for(namespace, relative).identity, flushed)
        client = self.client(self.backend('science'))
        client.acknowledge(self.pending, client.reconcile(self.pending))
        self.assertTrue(self.stage.deleted and self.slot.deleted)

    def test_claim_and_final_barrier_failures_remain_unconfirmed_then_recover(self):
        for suffix in ('.claim.json', '.event.json'):
            with self.subTest(suffix=suffix):
                self.native.fail_suffix = suffix
                with self.assertRaises(OSError):
                    ScienceCustodyFinalizer(self.writer).finalize(self.request)
                client = self.client(self.backend('science'))
                self.assertIsNone(client.reconcile(self.pending))
                self.assertFalse(self.stage.deleted or self.slot.deleted)
                self.native.role = 'writer'
        self.native.fail_suffix = None
        result = ScienceCustodyFinalizer(self.writer).finalize(self.request)
        self.assertIsNotNone(result)

    def test_existing_target_branch_cannot_convert_failed_flush_to_success(self):
        self.native.fail_receipt_flush = True
        with self.assertRaises(OSError):
            ScienceCustodyFinalizer(self.writer).finalize(self.request)
        relative = receipt_path(self.request.identity.digest())
        exact = self.object_for('receipts', relative)
        original = exact.raw, exact.identity
        with self.assertRaises(OSError):
            self.writer.create_trusted('receipts', relative, exact.raw)
        self.assertEqual(original, (exact.raw, exact.identity))
        self.assertNotIn(native_module._path_key(self.writer.namespace_root('receipts') /
                         completion_path(self.request.identity.digest())), self.native.objects)

    def test_science_cannot_flush_or_publish_completion(self):
        ScienceCustodyFinalizer(self.writer).finalize(self.request)
        reader = self.backend('science')
        relative = receipt_path(self.request.identity.digest())
        evidence = reader.read_trusted('receipts', relative, maximum=65536)
        before = len(self.native.flushes)
        with self.assertRaises(CustodyCommitIntegrityError):
            reader.ensure_durable('receipts', relative, evidence)
        with self.assertRaises(CustodyCommitIntegrityError):
            reader.publish_completion(completion_path(self.request.identity.digest()), b'{}')
        self.assertEqual(before, len(self.native.flushes))

    def test_reflush_rejects_different_native_object_without_flushing(self):
        ScienceCustodyFinalizer(self.writer).finalize(self.request)
        relative = receipt_path(self.request.identity.digest())
        evidence = self.writer.read_trusted('receipts', relative, maximum=65536)
        wrong = replace(evidence, file_identity=(99, 0, 100))
        before = len(self.native.flushes)
        with self.assertRaises(CustodyCommitIntegrityError):
            self.writer.ensure_durable('receipts', relative, wrong)
        self.assertEqual(before, len(self.native.flushes))

    def test_completion_is_only_visible_after_all_three_barriers(self):
        rename = self.native.rename
        observed = []
        def ordered(handle, target):
            if target.name.endswith('.complete.json'):
                for ns, rel in [('claims', claim_path(self.request.identity.digest())),
                                ('receipts', receipt_path(self.request.identity.digest())),
                                ('arrivals', self.request.final_relative_path)]:
                    identity = self.object_for(ns, rel).identity
                    self.assertTrue(any(row[0] == identity and row[2] for row in self.native.flushes))
                observed.append(True)
            return rename(handle, target)
        self.native.rename = ordered
        ScienceCustodyFinalizer(self.writer).finalize(self.request)
        self.assertEqual([True], observed)

    def test_lost_response_duplicate_does_not_reflush_or_republish(self):
        original = ScienceCustodyFinalizer(self.writer).finalize(self.request)
        before = len(self.native.flushes), len(self.native.renames)
        fresh = ScienceCustodyFinalizer(self.backend('writer'))
        self.assertEqual(original.receipt, fresh.finalize(self.request).receipt)
        self.assertEqual(before, (len(self.native.flushes), len(self.native.renames)))

    def test_conflicting_completion_and_replaced_receipt_refuse_ack(self):
        original = ScienceCustodyFinalizer(self.writer).finalize(self.request)
        completed = self.object_for('receipts', completion_path(self.request.identity.digest()))
        raw = completed.raw
        completed.raw = b'{"forged":true}\n'
        client = self.client(self.backend('science'))
        with self.assertRaises(CustodyCommitIntegrityError):
            client.acknowledge(self.pending, original)
        completed.raw = raw
        receipt = self.object_for('receipts', receipt_path(self.request.identity.digest()))
        receipt.identity = (9, 0, 999)
        with self.assertRaises(CustodyCommitIntegrityError):
            client.acknowledge(self.pending, original)
        self.assertFalse(self.stage.deleted or self.slot.deleted)


def client_for(backend):
    return ScienceCustodyMailboxClient(policy_sha256=backend.policy_sha256,
        source_root_identity=backend.source_root_identity, mailbox_backend=backend)


def stop_before_completion(phase):
    if phase == 'before_completion':
        raise CustodyCommitPending('deterministic interruption before announcement')


class ReadonlyRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='S016E-durability-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.backend = FilesystemProtocolFixture(self.root, start_writer=False)
        self.addCleanup(self.backend.close)
        self.client = client_for(self.backend)
        self.path, self.raw = arrival()

    def pending(self):
        return self.client.submit(final_root='arrivals', relative_path=self.path, raw=self.raw)

    def storage(self):
        return ScienceCustodyStorageSet(self.client, timeout_seconds=0.01, poll_seconds=0.005)

    def inventory(self):
        return {str(p.relative_to(self.root)): (p.stat().st_ino, sha256(p.read_bytes()))
                for p in self.root.rglob('*') if p.is_file()}

    def test_each_public_read_recovery_and_ack_path_rejects_unconfirmed(self):
        pending = self.pending()
        with self.assertRaises(CustodyCommitPending):
            ScienceCustodyFinalizer(self.backend, fault_hook=stop_before_completion).finalize(pending.request)
        exact = self.inventory()
        for fresh in (self.client, client_for(self.backend)):
            self.assertIsNone(fresh.reconcile(pending))
            self.assertEqual(pending, fresh.recover_pending())
            with self.assertRaises(CustodyCommitPending):
                fresh.read_confirmed('arrivals', self.path)
            raw = (self.backend.roots['receipts'] / receipt_path(pending.request.identity.digest())).read_bytes()
            with self.assertRaises(CustodyCommitIntegrityError):
                fresh.acknowledge(pending, CustodyCommitResult(CustodyCommitReceipt.from_bytes(raw), False, False))
        for _ in range(3):
            with self.assertRaises(CustodyCommitPending):
                self.storage()
        self.assertEqual(exact, self.inventory())

    def test_missing_stage_without_confirmation_is_not_recovered_as_success(self):
        pending = self.pending()
        with self.assertRaises(CustodyCommitPending):
            ScienceCustodyFinalizer(self.backend, fault_hook=stop_before_completion).finalize(pending.request)
        (self.backend.roots['staging'] / pending.request.staging_name).unlink()
        with self.assertRaises(CustodyCommitPending):
            client_for(self.backend).recover_pending()
        self.assertTrue((self.backend.roots['requests'] / 'request.json').exists())

    def test_legacy_receipt_empty_mailbox_reconfirmation_is_bounded_and_idempotent(self):
        pending = self.pending()
        finalizer = ScienceCustodyFinalizer(self.backend)
        result = finalizer.finalize(pending.request)
        self.client.acknowledge(pending, result)
        # Simulate old V1 custody / loss of the replayable observation, not an
        # untrusted Science permission test. Original three objects stay exact.
        (self.backend.roots['receipts'] / completion_path(pending.request.identity.digest())).unlink()
        committed = self.inventory()
        storage = self.storage()
        view = storage.storage('arrivals', expected_root=self.backend.roots['arrivals'],
                               source_root_identity=self.backend.source_root_identity)
        for _ in range(3):
            with self.assertRaises(CustodyCommitPending):
                view.read_committed(self.path)
        self.assertEqual(1, len(list(self.backend.roots['requests'].iterdir())))
        self.assertEqual(1, len(list(self.backend.roots['staging'].iterdir())))
        fresh = self.client.recover_pending()
        self.assertNotEqual(pending.request.generation, fresh.request.generation)
        self.assertEqual(pending.request.commit_binding(), fresh.request.commit_binding())
        repaired = self.backend.worker.poll_once()
        self.assertEqual(result.receipt, repaired.receipt)
        self.assertEqual(self.raw, view.read_committed(self.path))
        self.assertFalse(list(self.backend.roots['requests'].iterdir()))
        self.assertFalse(list(self.backend.roots['staging'].iterdir()))
        after = self.inventory()
        self.assertTrue(all(after[path] == value for path, value in committed.items()))
        before = self.backend.trusted_creates
        self.assertEqual(self.raw, view.read_committed(self.path))
        self.assertEqual(before, self.backend.trusted_creates)

    def test_new_publication_readback_does_not_bypass_owner_callback(self):
        storage = self.storage()
        def advance(pending):
            return self.backend.worker.poll_once()
        with patch.object(storage, '_await', side_effect=advance):
            storage.publish('arrivals', self.path, self.raw)
        self.assertEqual(self.raw, storage.read_committed('arrivals', self.path))
        self.assertTrue((self.backend.roots['requests'] / 'request.json').exists())
        storage.publication_verified('arrivals', self.path, self.raw)
        self.assertFalse((self.backend.roots['requests'] / 'request.json').exists())

    def test_crash_after_valid_ack_before_cleanup_and_partial_cleanup_recovers(self):
        pending = self.pending()
        result = self.backend.worker.poll_once()
        before = {p: value for p, value in self.inventory().items()
                  if not p.startswith(('staging', 'requests'))}
        def crash(phase):
            if phase == 'after_stage_cleanup':
                raise RuntimeError('Science exited during cleanup')
        client = ScienceCustodyMailboxClient(policy_sha256=self.backend.policy_sha256,
            source_root_identity=self.backend.source_root_identity, mailbox_backend=self.backend,
            fault_hook=crash)
        self.assertEqual(result.receipt, client.reconcile(pending).receipt)
        with self.assertRaises(RuntimeError):
            client.acknowledge(pending, result)
        self.storage()
        self.assertFalse(list(self.backend.roots['requests'].iterdir()))
        self.assertTrue(all(self.inventory()[p] == value for p, value in before.items()))


def _paused_writer(root, published, resume, outputs):
    backend = FilesystemProtocolFixture(Path(root), start_writer=False)
    flush = backend.ensure_durable
    def pause(namespace, relative, expected):
        if namespace == 'receipts' and relative.endswith('.commit.json'):
            published.set()
            if not resume.wait(15):
                raise RuntimeError('test coordinator did not release receipt barrier')
        return flush(namespace, relative, expected)
    backend.ensure_durable = pause
    try:
        result = backend.worker.poll_once()
        outputs.put(('writer', os.getpid(), result.receipt.receipt_identity))
    except BaseException as exc:
        outputs.put(('error', type(exc).__name__, str(exc)))
    finally:
        backend.close()


def _observing_science(root, outputs):
    backend = FilesystemProtocolFixture(Path(root), start_writer=False)
    client = client_for(backend)
    try:
        pending = client.recover_pending()
        result = client.reconcile(pending)
        evidence = backend.read_trusted('receipts', receipt_path(pending.request.identity.digest()), maximum=65536)
        visible = CustodyCommitResult(CustodyCommitReceipt.from_bytes(evidence.raw), False, False)
        refused = False
        try:
            client.acknowledge(pending, visible)
        except CustodyCommitIntegrityError:
            refused = True
        outputs.put(('science', os.getpid(), result is None, refused,
                     (backend.roots['staging'] / pending.request.staging_name).exists(),
                     (backend.roots['requests'] / 'request.json').exists()))
    except BaseException as exc:
        outputs.put(('error', type(exc).__name__, str(exc)))
    finally:
        backend.close()


def _recovery_writer(root, outputs):
    backend = FilesystemProtocolFixture(Path(root), start_writer=False)
    try:
        result = backend.worker.poll_once()
        outputs.put(('recovered', os.getpid(), result.receipt.receipt_identity))
    except BaseException as exc:
        outputs.put(('error', type(exc).__name__, str(exc)))
    finally:
        backend.close()


class SeparateProcessOrderingTests(unittest.TestCase):
    """Real processes and files; simulated principals, not Windows ACL proof."""
    setUp = ReadonlyRecoveryTests.setUp
    pending = ReadonlyRecoveryTests.pending

    def test_separate_science_while_writer_paused_then_writer_exit_and_recovery(self):
        pending = self.pending()
        ctx = multiprocessing.get_context('spawn')
        published, resume, outputs = ctx.Event(), ctx.Event(), ctx.Queue()
        writer = ctx.Process(target=_paused_writer, args=(str(self.root), published, resume, outputs))
        children = [writer]
        writer.start()
        try:
            self.assertTrue(published.wait(10), 'Writer never reached visible-receipt barrier')
            science = ctx.Process(target=_observing_science, args=(str(self.root), outputs))
            children.append(science)
            science.start()
            observed = outputs.get(timeout=10)
            science.join(10)
            self.assertEqual(0, science.exitcode)
            self.assertEqual('science', observed[0], observed)
            self.assertNotIn(observed[1], {os.getpid(), writer.pid})
            self.assertEqual((True, True, True, True), observed[2:])
            # Kill only the disposable process this test created, while held at
            # the deterministic barrier. No inference about power loss follows.
            writer.terminate()
            writer.join(10)
            self.assertFalse(writer.is_alive())
            self.assertIsNone(client_for(self.backend).reconcile(pending))
            replacement = ctx.Process(target=_recovery_writer, args=(str(self.root), outputs))
            children.append(replacement)
            replacement.start()
            recovered = outputs.get(timeout=10)
            replacement.join(10)
            self.assertEqual(0, replacement.exitcode)
            self.assertEqual('recovered', recovered[0], recovered)
            self.assertNotIn(recovered[1], {writer.pid, science.pid, os.getpid()})
            fresh_backend = FilesystemProtocolFixture(self.root, start_writer=False)
            self.addCleanup(fresh_backend.close)
            exact = fresh_backend.worker.poll_once()
            fresh = client_for(fresh_backend)
            self.assertEqual(exact.receipt, fresh.reconcile(pending).receipt)
            fresh.acknowledge(pending, exact)
            self.assertFalse(list(self.backend.roots['requests'].iterdir()))
            self.assertFalse(list(self.backend.roots['staging'].iterdir()))
        finally:
            # A terminated waiter may abandon Event's condition lock. Never
            # reuse its synchronization primitive after forced process exit.
            for child in children:
                if child.is_alive():
                    child.terminate()
                child.join(10)
                child.close()
            outputs.close()
            outputs.join_thread()


@unittest.skipUnless(os.name == 'nt', 'Canonical Science005 guards require Windows')
class CanonicalRecoveryCallerTests(unittest.TestCase):
    def opened(self, backend, publication_root):
        storage = ScienceCustodyStorageSet(client_for(backend), timeout_seconds=3)
        recorder = ContinuousScienceRecorder(publication_root, backend.science,
            source_root_identity=backend.source_root_identity, writer_instance_id='synthetic-durability-016e',
            clock=TickingClock(), custody_storage_set=storage)
        return recorder, storage

    def test_sealed_loaders_do_not_admit_unconfirmed_arrival_cursor_or_custody(self):
        for role in ('ARRIVAL', 'CURSOR', 'SOURCE', 'PAYLOAD', 'SCIENTIFIC_RECEIPT', 'CHECKPOINT'):
            with self.subTest(role=role), tempfile.TemporaryDirectory(prefix='S016E-caller-') as temp:
                root = Path(temp)
                producer = root / 'producer' / 'published'
                producer.mkdir(parents=True)
                backend = FilesystemProtocolFixture(root)
                replacement = recorder = reopened = None
                try:
                    publication(producer, core_fixtures()[0], 1)
                    recorder, storage = self.opened(backend, producer)
                    self.assertEqual(1, recorder.poll()['admitted'])
                    recorder.close()
                    recorder = None
                    backend.close()
                    claims = [(path, json.loads(path.read_bytes())) for path in backend.roots['claims'].rglob('*.claim.json')]
                    original = next(value['request'] for _, value in claims
                                    if value['request']['identity']['artifact_role'] == role)
                    from momentum_hunter.science_custody_commit import CustodyCommitRequest, canonical_protocol_bytes
                    request = CustodyCommitRequest.from_bytes(canonical_protocol_bytes(original))
                    completion = backend.roots['receipts'] / completion_path(request.identity.digest())
                    completion.unlink()  # Trusted legacy/lost-announcement fixture, never a Science ACL claim.
                    before = {p: (p.stat().st_ino, sha256(p.read_bytes()))
                              for base in (backend.science, backend.roots['claims'], backend.roots['receipts'])
                              for p in base.rglob('*') if p.is_file()}
                    blocked_storage = ScienceCustodyStorageSet(client_for(backend), timeout_seconds=0.01,
                                                               poll_seconds=0.005)
                    with self.assertRaises(CustodyCommitPending):
                        ContinuousScienceRecorder(producer, backend.science,
                            source_root_identity=backend.source_root_identity,
                            writer_instance_id='synthetic-durability-016e', clock=TickingClock(),
                            custody_storage_set=blocked_storage)
                    self.assertEqual(1, len(list(backend.roots['requests'].iterdir())))
                    self.assertTrue(all((p.stat().st_ino, sha256(p.read_bytes())) == value
                                        for p, value in before.items()))
                    replacement = FilesystemProtocolFixture(root)
                    reopened, _ = self.opened(replacement, producer)
                    self.assertEqual(0, reopened.poll()['admitted'])
                    self.assertEqual(1, reopened.reader.consume_available(max_items=0).cursor.last_publication_ordinal)
                    self.assertTrue(all((p.stat().st_ino, sha256(p.read_bytes())) == value
                                        for p, value in before.items()))
                    self.assertFalse(replacement.errors, replacement.errors)
                finally:
                    if recorder is not None:
                        recorder.close()
                    if reopened is not None:
                        reopened.close()
                    backend.close()
                    if replacement is not None:
                        replacement.close()

    def test_failed_cursor_publication_never_reaches_incremental_success_hook(self):
        with tempfile.TemporaryDirectory(prefix='S016E-cursor-') as temp:
            root = Path(temp)
            producer = root / 'producer' / 'published'
            producer.mkdir(parents=True)
            backend = FilesystemProtocolFixture(root)
            recorder = None
            try:
                recorder, storage = self.opened(backend, producer)
                publication(producer, core_fixtures()[0], 1)
                def fail_cursor(phase):
                    if phase == 'before_completion':
                        raw = (backend.roots['requests'] / 'request.json').read_bytes()
                        if json.loads(raw)['identity']['artifact_role'] == 'CURSOR':
                            backend.stop.set()
                            raise CustodyCommitPending('deterministic cursor interruption')
                backend.finalizer._fault_hook = fail_cursor
                storage.timeout_seconds = 0.1
                with patch.object(recorder.reader, '_cursor_committed', wraps=recorder.reader._cursor_committed) as advance:
                    with self.assertRaises(CustodyCommitPending):
                        recorder.poll()
                    self.assertEqual(0, advance.call_count)
                self.assertEqual(0, recorder.reader._view.last_publication_ordinal)
                self.assertTrue((backend.roots['requests'] / 'request.json').exists())
            finally:
                if recorder is not None:
                    recorder.close()
                backend.close()
if __name__ == '__main__':
    unittest.main()
