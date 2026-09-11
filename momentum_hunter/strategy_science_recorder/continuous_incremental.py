"""Science004 derived operation state; all durable formats remain raw custody.

Normal work visits new notifications and touched facts. Startup/recovery and
explicit historical APIs retain whole-corpus audits. Nothing here activates a
worker, producer, provider, service, scheduler, strategy or execution path.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import heapq
from pathlib import Path

from ..continuous_research_export import PUBLICATION_FILE
from .canonical import canonical_json_v1, parse_rfc3339, sha256_hex
from .contract import GENESIS_SHA256
from .verified_reads import VerifiedReads, VerifiedReadError, _identity
from .namespace_changes import DirectoryChanges
from .incremental_reader import IncrementalScienceReader
from .incremental_coverage import IncrementalCoverage
from .incremental_state import PublicHistory


class ContinuousIncremental:
    def __init__(self, owner):
        self.owner = owner
        self.depth = 0
        self.recovering = False
        self.needs_recovery = False
        self.ready = False
        self.producer_changes = self.producer_reads = self.ledger_changes = None
        self.names = {}
        self.observed = {}
        self.ordinal_heap = []
        self.unobserved_heap = []
        self.unobserved_names = set()
        self.updated = set()
        self.missing = {}
        self.ledger_names = set(owner._ledger_reads._entries)
        self.counters = {'producer_full_inventories': 0, 'producer_content_recoveries': 0, 'producer_names_visited': 0, 'normal_operations': 0, 'recovery_operations': 0}
        try:
            self.producer_changes = DirectoryChanges(owner.publication_root)
            self.producer_reads = VerifiedReads(owner.publication_root, aggregate_content=True)
            self.ledger_changes = DirectoryChanges(owner._storage.root, recursive=True)
            self._baseline_producer()
            self._reset_event_views()
            self.sync_events()
        except BaseException:
            self.close()
            raise

    def create_reader(self):
        return IncrementalScienceReader(self.owner.publication_root, self.owner.science_root / 'reader', recorder=self.owner.recorder, publication_index=lambda: self.observed)

    def _baseline_producer(self):
        self.counters['producer_full_inventories'] += 1
        actual = {path.name: path for path in self.owner.publication_root.iterdir()}
        for name in set(self.names) | set(actual):
            self._update_name(name)
        # An observed pending file may already be absent at process reopening.
        for name in self.owner._arrival_by_publication:
            if name != 'NOT_APPLICABLE':
                self._update_name(name)

    def _update_name(self, name):
        self.counters['producer_names_visited'] += 1
        path = self.owner.publication_root / name
        prior = self.owner._arrival_by_publication.get(name)
        if not path.exists():
            self.names.pop(name, None)
            match = PUBLICATION_FILE.fullmatch(name)
            if match is not None:
                ordinal = int(match.group('ordinal'))
                if self.observed.get(ordinal) == path:
                    self.observed.pop(ordinal)
            if prior is not None:
                self.missing[prior['arrival_id']] = {'kind': 'MISSING_OBSERVED_PUBLICATION', 'publication_file': name, 'arrival_id': prior['arrival_id']}
            return
        _identity(path)
        self.names[name] = path
        if prior is None:
            if name not in self.unobserved_names:
                self.unobserved_names.add(name)
                heapq.heappush(self.unobserved_heap, name)
        else:
            self.missing.pop(prior['arrival_id'], None)
            self.updated.add(name)

    def _reset_event_views(self):
        self.event_count = 0
        self.type_counts = Counter()
        self.raw_dispositions = Counter()
        self.first_receipt = self.last_receipt = None
        self.first_event = self.last_event = None
        self.max_event = None
        self.late = []
        self.clock_anomalies = []
        self.disordered = []
        self.gap_history = []
        self.last_gaps = []
        self.restarts = []
        self.source_sequence = {}
        self.source_event = {}
        self.source_owner = {}
        self.delivery_ordinal = {}

    def sync_events(self):
        if self.event_count > len(self.owner._events):
            raise VerifiedReadError('Derived event state is ahead of authoritative ledger.')
        for event in self.owner._events[self.event_count:]:
            kind, data = event['type'], event['data']
            self.type_counts[kind] += 1
            if kind == 'ARRIVAL':
                self.raw_dispositions[data['disposition']] += 1
                instant = parse_rfc3339(data['receipt_time'], 'first receipt')
                self.first_receipt = self._minimum(self.first_receipt, (instant, data['receipt_time']))
                self.last_receipt = self._maximum(self.last_receipt, (instant, data['receipt_time']))
                meta = data['metadata']
                if meta:
                    event_time = parse_rfc3339(meta['event_time'], 'producer event')
                    self.first_event = self._minimum(self.first_event, (event_time, meta['event_time']))
                    self.last_event = self._maximum(self.last_event, (event_time, meta['event_time']))
                    arrival = self.owner._arrival_by_delivery[(data['kind'], data['raw_sha256'], data['publication_file'])]
                    key = arrival['arrival_id']
                    lag = (instant - event_time).total_seconds()
                    if lag < 0:
                        self.clock_anomalies.append({'arrival_id': key, 'reason': 'RECEIPT_BEFORE_EVENT', 'delta_seconds': lag})
                    if self.owner.lateness_seconds is not None and lag > self.owner.lateness_seconds:
                        self.late.append({'arrival_id': key, 'delta_seconds': lag})
                    if self.max_event is not None and event_time < self.max_event:
                        self.disordered.append(key)
                    self.max_event = event_time if self.max_event is None else max(self.max_event, event_time)
                    self._register_identity(data)
            elif kind == 'GAPS':
                self.last_gaps = data['gaps']
                self.gap_history.append(dict(data, at=event['at']))
            elif kind == 'RESTART':
                self.restarts.append(event['at'])
        self.event_count = len(self.owner._events)

    @staticmethod
    def _minimum(prior, value):
        return value if prior is None or value[0] < prior[0] else prior

    @staticmethod
    def _maximum(prior, value):
        return value if prior is None or value[0] > prior[0] else prior

    def _keys(self, kind, meta):
        session = canonical_json_v1(meta['session_id'])
        stream = (kind, session, meta['stream_id'])
        return session, stream + (meta['source_sequence'],), stream + (meta['source_event_id'],)

    def _register_identity(self, data):
        kind, meta = data['kind'], data['metadata']
        session, sequence, event = self._keys(kind, meta)
        self.source_sequence.setdefault(sequence, data['raw_sha256'])
        self.source_event.setdefault(event, data['raw_sha256'])
        if kind == 'PUBLICATION':
            match = PUBLICATION_FILE.fullmatch(data['publication_file'])
            if match is not None:
                self.delivery_ordinal.setdefault(int(match.group('ordinal')), data['raw_sha256'])
            self.source_owner.setdefault(session, (meta['source_owner_identity'], meta['source_interface_identity']))

    def collision(self, kind, meta, name):
        session, sequence, event = self._keys(kind, meta)
        if sequence in self.source_sequence or event in self.source_event:
            return True
        if kind == 'PUBLICATION':
            match = PUBLICATION_FILE.fullmatch(name)
            return (match is not None and int(match.group('ordinal')) in self.delivery_ordinal) or (session in self.source_owner and self.source_owner[session] != (meta['source_owner_identity'], meta['source_interface_identity']))
        return False

    def finish_open(self):
        # Complete old-publication registration during STARTUP, not on the
        # first normal poll. A changed pending postimage remains to be staged
        # explicitly; exact unchanged old files need no normal history pass.
        for name in tuple(self.updated):
            path = self.names.get(name)
            prior = self.owner._arrival_by_publication[name]
            if path is not None and sha256_hex(self.producer_reads.read(path)) == prior['raw_sha256']:
                match = PUBLICATION_FILE.fullmatch(name)
                if match is not None:
                    ordinal = int(match.group('ordinal'))
                    if ordinal in self.observed and self.observed[ordinal] != path:
                        raise VerifiedReadError('Startup publication ordinal is ambiguous.')
                    self.observed[ordinal] = path
                    heapq.heappush(self.ordinal_heap, ordinal)
                self.updated.discard(name)
        self.rebuild_coverage()
        self.ready = True

    def rebuild_coverage(self):
        self.coverage = IncrementalCoverage()
        phase = {'session-manifest': 0, 'discovery-cycle': 1, 'candidate-observation': 2, 'science-eligibility': 3, 'decision-event': 4, 'outcome-observation': 6}
        for record in sorted(self.owner.records(), key=lambda record: phase.get(record['record_type'], 5)):
            self.coverage.add(record)

    def ledger_published(self, path):
        self.ledger_names.add(path)

    def _check_ledger(self):
        self.owner._ledger_reads.check_content()
        for name in self.ledger_changes.drain():
            path = self.owner._storage.root / name
            if Path(name).parts[0] != 'ledger':
                continue
            if name == 'ledger':
                if not path.is_dir() or path.is_symlink():
                    raise VerifiedReadError('Ledger directory is missing or redirected.')
                continue
            if path not in self.ledger_names:
                raise VerifiedReadError('Ledger namespace is ahead of locally verified commits.')
            self.owner._ledger_reads.read(path)
        self.owner._ledger_reads.check_content()

    def ensure_ready(self):
        if not self.needs_recovery or self.recovering or self.owner._frozen():
            return
        self.recovering = True
        self.counters['recovery_operations'] += 1
        try:
            self.owner._load(force=True)
            self.owner._reindex()
            self.owner.recorder.recover()
            self.owner.reader._view = None
            self.owner.reader._load_state()
            self.owner._synchronize(recovery=True)
            self.rebuild_coverage()
            self.owner.recorder._views.failed = False
            self.needs_recovery = False
        finally:
            self.recovering = False

    @contextmanager
    def operation(self):
        if self.owner._frozen():
            raise self.owner._frozen_error('Persisted invalid/conflicting input freezes this recorder root.')
        self.ensure_ready()
        self.counters['normal_operations'] += 1
        with self.owner._storage.transaction(), self.owner.recorder._views.incremental_operation():
            self._check_ledger()
            self.depth += 1
            self.owner._operation_depth += 1
            self.owner._ledger_loaded = True
            try:
                yield
                self.sync_events()
                self._check_ledger()
                self.owner.reader._check_cursor()
                self._check_producer_boundary()
            except BaseException:
                self.needs_recovery = not self.owner._frozen()
                raise
            finally:
                self.owner._operation_depth -= 1
                self.depth -= 1

    def _check_producer_boundary(self):
        try:
            self.producer_reads.check_content()
        except VerifiedReadError:
            # A write racing admission must not return an apparently healthy
            # boundary. Retain any changed surviving bytes as a conflicting
            # arrival during exceptional reconciliation, then fail this call.
            # No prior Science observation is rewritten or reclassified.
            self.observe(0, None)
            raise

    def observe(self, budget, crash_phase):
        for name in self.producer_changes.drain():
            if '/' in name:
                raise VerifiedReadError('Producer publication namespace is not flat.')
            self._update_name(name)
        try:
            self.producer_reads.check_content()
        except VerifiedReadError:
            # An exceptional write to old Producer content requires a full
            # current-state reconciliation. The original bytes remain in the
            # immutable Science arrival ledger; changed bytes are staged below.
            self.counters['producer_content_recoveries'] += 1
            self.producer_reads.close()
            self.producer_reads = VerifiedReads(self.owner.publication_root, aggregate_content=True)
            self._baseline_producer()
        observed = 0
        names = sorted(self.updated)
        while self.unobserved_heap and observed < budget:
            name = heapq.heappop(self.unobserved_heap)
            self.unobserved_names.discard(name)
            if name in self.names:
                names.append(name)
                observed += 1
        processed = set()
        try:
            for name in names:
                path = self.names.get(name)
                if path is not None:
                    raw = self.producer_reads.read(path)
                    self.owner._stage(raw, 'PUBLICATION', name, crash_phase, count_duplicate=False)
                    match = PUBLICATION_FILE.fullmatch(name)
                    if match is not None:
                        ordinal = int(match.group('ordinal'))
                        if ordinal in self.observed and self.observed[ordinal] != path:
                            raise self.owner._read_integrity_error('Duplicate publication ordinal.')
                        if ordinal not in self.observed:
                            heapq.heappush(self.ordinal_heap, ordinal)
                        self.observed[ordinal] = path
                self.updated.discard(name)
                processed.add(name)
        finally:
            # Interruption may occur after a raw receipt but before the local
            # publication index. Keep every unprocessed delivery discoverable
            # for same-instance recovery as well as a cold restart.
            for name in names:
                if name not in processed and name not in self.unobserved_names:
                    self.unobserved_names.add(name)
                    heapq.heappush(self.unobserved_heap, name)
        self.producer_reads.check_content()
        return observed, self.observed, list(self.missing.values())

    def future(self, expected):
        while self.ordinal_heap and (self.ordinal_heap[0] < expected or self.ordinal_heap[0] not in self.observed):
            heapq.heappop(self.ordinal_heap)
        return self.ordinal_heap[0] if self.ordinal_heap else None

    def apply_records(self, pairs):
        for record, raw in pairs:
            self.coverage.add(record, raw)

    def summary(self, families):
        self.sync_events()
        if self.event_count != len(self.owner._events) or self.type_counts['ARRIVAL'] != len(self.owner._arrivals):
            raise VerifiedReadError('Derived arrival counts disagree with raw ledger.')
        received = self.raw_dispositions['RECEIVED']
        # Invalid/conflicting arrivals freeze before admission. Rejected markers
        # bind RECEIVED arrivals; raw invalid inputs keep separate dispositions.
        pending = received - len(self.owner._admitted) - len(self.owner._rejected)
        if pending < 0:
            raise VerifiedReadError('Derived pending count is contradictory.')
        text = lambda pair: pair[1] if pair is not None else None
        return {'family_counts': {family: self.coverage.families[family] for family in families}, 'normalized_record_count': len(self.coverage.hashes), 'raw_arrival_count': len(self.owner._arrivals), 'admitted_arrival_count': len(self.owner._admitted), 'pending_count': pending, 'conflicts': self.raw_dispositions['CONFLICT'], 'invalid_count': self.raw_dispositions['INVALID'], 'rejected_count': len(self.owner._rejected), 'admission_frozen': self.owner._frozen(), 'duplicate_deliveries': self.type_counts['DUPLICATE'], 'first_receipt_time': text(self.first_receipt), 'last_receipt_time': text(self.last_receipt), 'first_event_time': text(self.first_event), 'last_event_time': text(self.last_event), 'late_arrivals': PublicHistory(self.late), 'clock_anomalies': PublicHistory(self.clock_anomalies), 'event_time_disordered_arrivals': PublicHistory(self.disordered), 'gaps': deepcopy(self.last_gaps), 'gap_history': PublicHistory(self.gap_history), 'restart_boundaries': PublicHistory(self.restarts), 'lateness_policy_seconds': self.owner.lateness_seconds, 'lateness_classification': 'UNKNOWN' if self.owner.lateness_seconds is None else 'EXPLICIT_POLICY', 'capture_classification': 'UNKNOWN_NO_SCHEDULER_TARGET_POLICY', 'canonical': self.coverage.snapshot(conflicts=self.raw_dispositions['CONFLICT']), 'retention': 'APPEND_ONLY_NO_DELETION', 'continuous_coverage': 'NOT_PROVEN', 'independent_sample_count': 'NOT_PROVEN', 'execution_authority': 'NONE', 'proof_scope': 'NEW_COMMIT_DELTA_WITH_CONTENT_COHERENCE; FULL_NAMESPACE_AUDIT_EXPLICIT_OR_RECOVERY', 'historical_export': 'Use coverage() for full audited JSON and source/session inventories.'}

    def close(self):
        errors = []
        for guard in (self.producer_changes, self.producer_reads, self.ledger_changes):
            if guard is not None:
                try:
                    guard.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]
