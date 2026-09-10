from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import traceback
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from momentum_hunter.schwab_auth_lock import SchwabAuthStateLock
from momentum_hunter.schwab_market_data import (
    SchwabAuthPersistenceFailed, SchwabAuthSecureStoreError, SchwabAuthRefreshFailed,
    SchwabReadOnlyAccessTokenProvider,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthSecretRepository
from momentum_hunter.schwab_setup import LocalSecretStore, SchwabApplicationCredentials
from tests.test_schwab_auth_lifecycle import _tokens, _RefreshTransport


class _SyntheticProtector:
    def protect(self, value):
        return bytes(b ^ 93 for b in value)

    def unprotect(self, value):
        return bytes(b ^ 93 for b in value)


def _noop_permissions(path):
    pass


def _repository(root):
    return SchwabOAuthSecretRepository(store=LocalSecretStore(
        path=Path(root) / 'synthetic-store.dat', protector=_SyntheticProtector(),
        permission_hardener=_noop_permissions))


def _seed(root):
    repo = _repository(root)
    repo.save_new_credentials(SchwabApplicationCredentials('SYNTHETIC-ID', 'SYNTHETIC-SECRET'))
    repo.save_tokens(_tokens('SYNTHETIC-EXPIRED', expired=True))
    (Path(root) / 'refresh-count.txt').write_text('0', encoding='ascii')
    return repo


class _CountRefresh:
    def __init__(self, root):
        self.path = Path(root) / 'refresh-count.txt'

    def refresh(self, credentials, current):
        n = int(self.path.read_text(encoding='ascii')) + 1
        self.path.write_text(str(n), encoding='ascii')
        return _tokens('SYNTHETIC-NEW', expired=False)


def _safe_exception(exc):
    chain = []
    while exc is not None:
        chain.append({'type': type(exc).__name__, 'message': str(exc),
                      'errno': getattr(exc, 'errno', None), 'winerror': getattr(exc, 'winerror', None),
                      'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                                 for f in traceback.extract_tb(exc.__traceback__)]})
        exc = exc.__cause__
    return chain


def _actor(root, role, opened, release, writer_started, save_started, results):
    repo = _repository(root)
    if role == 'reader':
        original_load = repo.load_tokens
        first = True

        def held_load():
            nonlocal first
            if first:
                first = False
                with repo.store.path.open('rb') as handle:
                    opened.set()
                    if not release.wait(15):
                        raise TimeoutError('synthetic reader release timeout')
                    handle.read()
            return original_load()

        repo.load_tokens = held_load
    else:
        original_save = repo.save_tokens_under_ownership

        def observed_save(tokens):
            save_started.set()
            return original_save(tokens)

        repo.save_tokens_under_ownership = observed_save
        writer_started.set()
    provider = SchwabReadOnlyAccessTokenProvider(
        secrets_repository=repo, oauth_transport=_CountRefresh(root))
    record = {'role': role, 'pid': os.getpid(), 'target': str(repo.store.path),
              'startedNs': time.time_ns()}
    try:
        record['pass'] = provider.access_token() == 'SYNTHETIC-NEW'
    except Exception as exc:
        record['pass'] = False
        record['exceptionChain'] = _safe_exception(exc)
    record['finishedNs'] = time.time_ns()
    results.put(record)


def _writer(root, name, start, results):
    try:
        start.wait(15)
        _repository(root).save_tokens(_tokens(name, expired=False))
        results.put({'pass': True, 'pid': os.getpid()})
    except Exception as exc:
        results.put({'pass': False, 'exceptionChain': _safe_exception(exc)})


class SchwabAuthPersistenceConcurrencyTests(unittest.TestCase):
    def test_read_ownership_timeout_is_bounded_and_never_refreshes(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            transport = _RefreshTransport()
            repo.refresh_ownership = lambda: SchwabAuthStateLock(
                repo.store.path, timeout_seconds=0.1, poll_seconds=0.01)
            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=transport)
            with SchwabAuthStateLock(repo.store.path):
                started = time.monotonic()
                with self.assertRaises(SchwabAuthRefreshFailed):
                    provider.access_token()
                self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(0, transport.calls)

    def test_initial_read_participates_in_refresh_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            held = False
            original_load = repo.load_tokens
            original_ownership = repo.refresh_ownership

            @contextmanager
            def ownership():
                nonlocal held
                with original_ownership():
                    self.assertFalse(held, 'ownership must not be nested')
                    held = True
                    try:
                        yield
                    finally:
                        held = False

            def checked_load():
                self.assertTrue(held, 'unowned initial read races atomic replacement')
                return original_load()

            repo.refresh_ownership = ownership
            repo.load_tokens = checked_load
            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=_RefreshTransport())
            self.assertEqual('SYNTHETIC-REFRESHED', provider.access_token())

    @unittest.skipUnless(os.name == 'nt', 'physical Windows read-handle semantics')
    def test_reader_handle_and_refresh_writer_are_serialized_across_processes(self):
        with tempfile.TemporaryDirectory() as root:
            _seed(root)
            ctx = multiprocessing.get_context('spawn')
            opened, release, started, saving = [ctx.Event() for _ in range(4)]
            results = ctx.Queue()
            actors = []
            rows = []
            try:
                reader = ctx.Process(target=_actor, args=(root, 'reader', opened, release, started, saving, results))
                reader.start()
                actors.append(reader)
                self.assertTrue(opened.wait(15), 'reader failed to open fixture')
                writer = ctx.Process(target=_actor, args=(root, 'writer', opened, release, started, saving, results))
                writer.start()
                actors.append(writer)
                self.assertTrue(started.wait(15), 'writer failed to start')
                overlapped = saving.wait(0.75)
                if overlapped:
                    rows.append(results.get(timeout=10))
                release.set()
                rows.extend(results.get(timeout=20) for _ in range(len(actors) - len(rows)))
                for actor in actors:
                    actor.join(20)
                diagnostic = {'rows': rows, 'saveWhileReadHandleOpen': overlapped,
                              'refreshCount': (Path(root)/'refresh-count.txt').read_text(encoding='ascii')}
                destination = os.environ.get('F1_MATRIX_DIAGNOSTICS')
                if destination:
                    with Path(destination).open('x', encoding='utf-8') as stream:
                        json.dump(diagnostic, stream, indent=2)
                self.assertEqual([0, 0], [a.exitcode for a in actors])
                self.assertFalse(overlapped, diagnostic)
                self.assertTrue(all(r['pass'] for r in rows), diagnostic)
                self.assertEqual('1', diagnostic['refreshCount'])
                self.assertEqual('SYNTHETIC-NEW', _repository(root).load_tokens().access_token)
            finally:
                release.set()
                for actor in actors:
                    actor.join(5)
                    if actor.is_alive():
                        actor.terminate()
                        actor.join(5)
                results.close()
                results.join_thread()

    def test_simultaneous_writers_serialize_and_preserve_complete_state(self):
        with tempfile.TemporaryDirectory() as root:
            _seed(root)
            ctx = multiprocessing.get_context('spawn')
            start, results = ctx.Event(), ctx.Queue()
            actors = [ctx.Process(target=_writer, args=(root, name, start, results))
                      for name in ('SYNTHETIC-A', 'SYNTHETIC-B')]
            try:
                for actor in actors:
                    actor.start()
                start.set()
                rows = [results.get(timeout=20) for _ in actors]
                for actor in actors:
                    actor.join(20)
                self.assertEqual([0, 0], [a.exitcode for a in actors])
                self.assertTrue(all(r['pass'] for r in rows), rows)
                repo = _repository(root)
                self.assertIn(repo.load_tokens().access_token, ('SYNTHETIC-A', 'SYNTHETIC-B'))
                self.assertEqual('SYNTHETIC-ID', repo.load_credentials().application_id)
                self.assertEqual([], list(Path(root).glob('*.tmp')))
            finally:
                for actor in actors:
                    actor.join(5)
                    if actor.is_alive():
                        actor.terminate()
                        actor.join(5)
                results.close()
                results.join_thread()

    @unittest.skipUnless(os.name == 'nt', 'physical Windows read-handle semantics')
    def test_nonparticipating_held_handle_fails_closed_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            before = repo.store.path.read_bytes()
            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=_RefreshTransport())
            with repo.store.path.open('rb'):
                with self.assertRaises(SchwabAuthPersistenceFailed) as caught:
                    provider.access_token()
            self.assertIsInstance(caught.exception.__cause__, PermissionError)
            self.assertIn(caught.exception.__cause__.winerror, (5, 32))
            self.assertEqual(before, repo.store.path.read_bytes())
            self.assertEqual([], list(Path(root).glob('*.tmp')))
            self.assertEqual(0, provider.metrics.refresh_successes)

    def test_failed_replace_never_succeeds_or_removes_prior_state(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            before = repo.store.path.read_bytes()
            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=_RefreshTransport())
            with patch.object(Path, 'replace', side_effect=PermissionError('synthetic denied replace')):
                with self.assertRaises(SchwabAuthPersistenceFailed):
                    provider.access_token()
            self.assertEqual(before, repo.store.path.read_bytes())
            self.assertEqual([], list(Path(root).glob('*.tmp')))
            self.assertEqual(0, provider.metrics.refresh_successes)
            self.assertNotIn('SYNTHETIC', json.dumps(provider.metrics_snapshot()))

    def test_partial_temporary_write_is_cleaned_without_mutating_committed_state(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            before = repo.store.path.read_bytes()
            original_write = Path.write_bytes

            def partial_write(path, content):
                if path.suffix == '.tmp':
                    original_write(path, content[:5])
                    raise OSError('synthetic partial temporary write')
                return original_write(path, content)

            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=_RefreshTransport())
            with patch.object(Path, 'write_bytes', partial_write):
                with self.assertRaises(SchwabAuthPersistenceFailed):
                    provider.access_token()
            self.assertEqual(before, repo.store.path.read_bytes())
            self.assertEqual([], list(Path(root).glob('*.tmp')))
            self.assertEqual(0, provider.metrics.refresh_successes)

    def test_peer_persistence_before_local_refresh_is_adopted_without_second_refresh(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            original = repo.refresh_ownership
            entries = 0

            @contextmanager
            def ownership():
                nonlocal entries
                entries += 1
                with original():
                    if entries == 2:
                        repo.save_tokens_under_ownership(_tokens('SYNTHETIC-PEER', expired=False))
                    yield

            repo.refresh_ownership = ownership
            transport = _RefreshTransport()
            provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=transport)
            self.assertEqual('SYNTHETIC-PEER', provider.access_token())
            self.assertEqual(0, transport.calls)

    def test_duplicate_persistence_and_restart_adopt_without_refresh(self):
        with tempfile.TemporaryDirectory() as root:
            repo = _seed(root)
            value = _tokens('SYNTHETIC-VALID', expired=False)
            repo.save_tokens(value)
            before = repo.store.load()
            repo.save_tokens(value)
            self.assertEqual(before, repo.store.load())
            transport = _RefreshTransport()
            restarted = SchwabReadOnlyAccessTokenProvider(secrets_repository=_repository(root), oauth_transport=transport)
            self.assertEqual('SYNTHETIC-VALID', restarted.access_token())
            self.assertEqual(0, transport.calls)

    def test_corrupt_and_partial_state_fail_closed_without_refresh(self):
        for value in (b'not-base64!', b'eA==', b''):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as root:
                repo = _seed(root)
                repo.store.path.write_bytes(value)
                transport = _RefreshTransport()
                provider = SchwabReadOnlyAccessTokenProvider(secrets_repository=repo, oauth_transport=transport)
                with self.assertRaises(SchwabAuthSecureStoreError):
                    provider.access_token()
                self.assertEqual(0, transport.calls)
                self.assertEqual(value, repo.store.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
