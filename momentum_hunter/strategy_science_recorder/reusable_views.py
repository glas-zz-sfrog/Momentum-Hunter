"""Secondary, process-local custody views over exact guarded raw evidence.

No new disk format, durable index, clock or source of authority. Startup,
recovery and explicit historical APIs audit the full namespace and singleton
metadata. The opt-in Continuous normal path checks content invalidation,
namespace notifications and exact newly committed/touched evidence instead.
Content coherence is not proof of historical hard-link metadata invariance.
"""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path, PurePath
from collections.abc import Mapping
from collections.abc import Sequence

from .canonical import canonical_json_bytes

from .verified_reads import VerifiedReads, VerifiedReadError, _directory_identity, _identity
from .namespace_changes import DirectoryChanges


class HistoryView(Sequence):
    """Constant-size snapshot of a private append-only history.

    Iteration/materialization is explicit O(history); normal append is not.
    Values belong to the owning private index, never a mutable public result.
    """
    def __init__(self, items=None, index=None, length=None):
        self._items = [] if items is None else items
        self._index = {} if index is None else index
        self._length = len(self._items) if length is None else length

    def __len__(self):
        return self._length

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self._items[i] for i in range(*index.indices(self._length)))
        if index < 0:
            index += self._length
        if not 0 <= index < self._length:
            raise IndexError(index)
        return self._items[index]

    def extended(self, values):
        if self._length != len(self._items):
            raise VerifiedReadError('Attempt to extend a stale derived history view.')
        for value in values:
            key = value['source_event_id']
            if key in self._index:
                raise VerifiedReadError('Duplicate checkpoint event in derived history.')
            self._index[key] = len(self._items)
            self._items.append(value)
        return HistoryView(self._items, self._index)

    def matching(self, event_id):
        position = self._index.get(event_id)
        return () if position is None or position >= self._length else (self._items[position],)


class ReusableViews:
    def __init__(self, storage):
        self.storage = storage
        self.reads = VerifiedReads(storage.root, aggregate_content=True)
        try:
            self.changes = DirectoryChanges(storage.root, recursive=True)
        except BaseException:
            self.reads.close()
            raise
        self.directories = {}
        self.incremental = False
        self.failed = False
        self.depth = 0
        self.namespace = None
        self.queries = {}
        self.query_directories = {}
        self.channels = {}
        self.streams = {}
        self.memo = {}
        self.json = {}
        self.payload_index = None
        self.record_index = None
        self.secondary = {}
        self.generation = 0
        self.counters = {"namespace_audits": 0, "namespace_entries": 0,
                         "channel_rebuilds": 0, "channel_tail_payloads": 0,
                         "channel_tail_receipts": 0, "memo_hits": 0}

    def _inventory(self):
        paths = self.storage.iter_files(PurePath('sessions'), suffix='')
        self._remember_directory(PurePath('sessions'))
        self.counters['namespace_audits'] += 1
        self.counters['namespace_entries'] += len(paths)
        for path in paths:
            parent = path.parent
            while parent != self.storage.root:
                self.directories[parent] = _directory_identity(parent)
                parent = parent.parent
        return set(paths)

    def _remember_directory(self, relative):
        # Canonical iter_files pins/creates the explicitly requested directory,
        # including an empty channel. Record that owned API delta as well as
        # parents of files; never accept an arbitrary notified directory here.
        parent = self.storage.root / Path(relative)
        while parent != self.storage.root and parent.is_dir():
            self.directories[parent] = _directory_identity(parent)
            parent = parent.parent

    def check_changes(self):
        self.reads.check_content()
        for name in self.changes.drain():
            relative = PurePath(name)
            if relative.parts[0] != 'sessions':
                continue  # Owner/partial/quarantine have separate explicit rules.
            path = self.storage.root / Path(relative)
            if path in self.directories:
                if _directory_identity(path) != self.directories[path]:
                    raise VerifiedReadError('Known custody directory changed identity.')
            elif self.namespace is not None and path in self.namespace:
                _identity(path)
                if path in self.reads._entries:
                    self.reads.read(path)
            else:
                raise VerifiedReadError(f'Custody namespace changed outside local committed deltas: {name}')
        self.reads.check_content()

    @contextmanager
    def incremental_operation(self):
        if self.failed or self.namespace is None:
            raise VerifiedReadError('A startup-verified custody generation is required.')
        prior = self.incremental
        self.incremental = True
        try:
            with self.operation():
                yield
        except BaseException:
            self.failed = True
            raise
        finally:
            self.incremental = prior

    @contextmanager
    def operation(self):
        if self.incremental:
            with self.storage.transaction():
                outer = not self.depth
                if outer:
                    self.check_changes()
                self.depth += 1
                try:
                    yield
                    if outer:
                        self.check_changes()
                except BaseException:
                    self.failed = True
                    self.invalidate_semantic()
                    raise
                finally:
                    self.depth -= 1
            return
        # The storage lock remains the owner lock; no replacement writer policy.
        with self.storage.transaction(), self.reads.operation():
            outer = not self.depth
            if outer:
                current = self._inventory()
                if self.namespace is not None and not self.namespace.issubset(current):
                    raise VerifiedReadError('Known custody namespace lost an immutable object.')
                if self.namespace != current:
                    self.queries.clear()
                    self.query_directories.clear()
                    self.channels.clear()
                    self.streams.clear()
                    self.memo.clear()
                    self.payload_index = self.record_index = None
                    self.secondary.clear()
                    self.generation += 1
                self.namespace = current
                self.changes.drain()  # Full inventory just established the baseline.
            self.depth += 1
            try:
                if outer:
                    # Explicit historical scopes also audit parsed secondary
                    # values. A healthy file lease cannot certify an altered
                    # in-memory JSON object. This full walk never runs in the
                    # separately selected normal incremental branch above.
                    for path, value in self.json.items():
                        if canonical_json_bytes(value) != self.reads.read(path):
                            raise VerifiedReadError('Parsed historical view differs from guarded raw authority.')
                yield
                if outer and self._inventory() != self.namespace:
                    raise VerifiedReadError('Custody namespace changed outside the owned publication path.')
            except BaseException:
                # A failed append may have installed raw custody before an index
                # update. Never retain a speculative semantic view across it.
                self.failed = True
                self.queries.clear()
                self.query_directories.clear()
                self.channels.clear()
                self.streams.clear()
                self.memo.clear()
                self.payload_index = self.record_index = None
                self.secondary.clear()
                self.generation += 1
                raise
            finally:
                self.depth -= 1

    def invalidate_semantic(self):
        self.queries.clear()
        self.query_directories.clear()
        self.channels.clear()
        self.streams.clear()
        self.memo.clear()
        self.payload_index = self.record_index = None
        self.secondary.clear()
        self.generation += 1

    def files(self, relative, suffix):
        # Partial/quarantine namespaces are not append-only canonical custody:
        # quarantine moves their entries, including between two recover calls.
        if not self.depth or not PurePath(relative).parts or PurePath(relative).parts[0] != 'sessions':
            return self.storage.iter_files(relative, suffix=suffix)
        key = (PurePath(relative), suffix)
        if key not in self.queries:
            self.queries[key] = list(self.storage.iter_files(relative, suffix=suffix))
            self._remember_directory(relative)
            self.query_directories.setdefault(PurePath(relative),set()).add(suffix)
        return self.queries[key]

    def published(self, relative):
        path = self.storage.root / Path(relative)
        parent = path.parent
        while parent != self.storage.root:
            self.directories[parent] = _directory_identity(parent)
            parent = parent.parent
        if self.namespace is not None and Path(relative).parts[0] == 'sessions':
            if path in self.namespace:
                return
            self.namespace.add(path)
        directory = PurePath(relative).parent
        while directory.parts:
            for suffix in self.query_directories.get(directory,()):
                if path.name.endswith(suffix):
                    self.queries[(directory,suffix)].append(path)
            directory = directory.parent
        self.memo.clear()
        self.generation += 1

    def close(self):
        try:
            self.changes.close()
        finally:
            self.reads.close()
        self.queries.clear()
        self.query_directories.clear()
        self.channels.clear()
        self.streams.clear()
        self.memo.clear()
        self.json.clear()
        self.payload_index = self.record_index = None


def custody_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if self._views is None:
            return method(self, *args, **kwargs)
        try:
            with self._views.operation():
                return method(self, *args, **kwargs)
        except VerifiedReadError as exc:
            # Import locally to keep the custody error hierarchy canonical.
            from .custody import RecorderRecoveryError
            raise RecorderRecoveryError(str(exc)) from exc
    return guarded


def reusable_view(method):
    """Reuse only within the unchanged, physically guarded custody generation."""
    @wraps(method)
    def cached(self, *args):
        if self._views is None or not self._views.depth:
            return method(self, *args)
        key = (method.__name__, tuple(canonical_json_bytes(arg) if isinstance(arg, Mapping) else arg for arg in args))
        if key not in self._views.memo:
            self._views.memo[key] = method(self, *args)
        else:
            self._views.counters['memo_hits'] += 1
        return self._views.memo[key]
    return cached


def continuous_public_operation(method):
    """Use the existing Science custody boundary for the receipt-ledger owner."""
    @wraps(method)
    def scoped(self, *args, **kwargs):
        try:
            support = getattr(self, '_support', None)
            if support is not None and (support.depth or support.recovering):
                return method(self, *args, **kwargs)
            if support is not None and support.ready:
                if method.__name__ in {'poll', 'append_outcome'}:
                    with support.operation():
                        return method(self, *args, **kwargs)
            with continuous_operation(self):
                return method(self, *args, **kwargs)
        except VerifiedReadError as exc:
            raise self._read_integrity_error(str(exc)) from exc
    return scoped


def build_incremental_support(owner):
    # Lazy import avoids a custody/Reader import cycle. This only constructs
    # explicitly caller-owned, dormant Science state, never a background worker.
    from .continuous_incremental import ContinuousIncremental
    return ContinuousIncremental(owner)


@contextmanager
def continuous_operation(owner):
    if owner._closed:
        raise VerifiedReadError('Recorder is closed.')
    assert owner.recorder is not None and owner._ledger_reads is not None
    outer = not owner._operation_depth
    with owner._storage.transaction(), owner._ledger_reads.operation(), owner.recorder._views.operation():
        if outer:
            owner._ledger_loaded = False
        owner._operation_depth += 1
        try:
            yield
            if outer:
                owner._load(force=True)
        finally:
            owner._operation_depth -= 1
