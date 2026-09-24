"""Dormant Science-side views: only the existing trusted Writer publishes raw.

Receipt reconciliation is a transport operation, never scientific admission.
An outstanding publication is acknowledged only after the owner has completed
its exact readback and Science005 singleton registration/notification drain.
Legacy offline storage remains a distinct, non-physical-isolation mode.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePath
import threading
import time

from .science_custody_commit import CustodyCommitError, CustodyCommitPending
from .science_custody_mailbox import ScienceCustodyMailboxClient
from .windows_writer_storage import WriterPhysicalStorageError


SCIENCE_STORAGE_ROLE_SECURITY_CONTRACT = {
    'version': 'SCIENCE_STORAGE_ROLES_007_V1',
    'owner': 'EXISTING_CONTINUOUS_WRITER_ACCOUNT_DOMAIN',
    'science_staging': 'SCIENCE_CREATE_WRITE_FLUSH_READ_RENAME_DELETE_TEMP_ONLY',
    'committed_raw_custody': 'SCIENCE_READ_AUDIT_ONLY_WRITER_OWNED',
    'derived_rebuildable_state': 'SCIENCE_MUTABLE_NOT_RAW_AUTHORITY',
    'logs': 'SCIENCE_OPERATIONAL_LOG_ONLY_NO_RAW_AUTHORITY',
    'config': 'SCIENCE_READ_ONLY_NO_ACCOUNT_ROOT_OR_PERMISSION_REBIND',
    # File rights; directory 0x2/0x4 are ADD_FILE/ADD_SUBDIRECTORY.
    'committed_forbidden_file_rights': (0x2, 0x4, 0x10000, 0x40000, 0x80000),
    'committed_forbidden_directory_rights': (0x2, 0x4, 0x40, 0x10000, 0x40000, 0x80000),
    'replaceable_ancestors': 'NON_SCIENCE_OWNER_NO_SCIENCE_MUTATION',
    'readiness_requires': 'NATIVE_TOKEN_OWNER_DACL_ROOT_AND_ANCESTOR_BINDINGS',
    'legacy_offline_storage_qualifies': False,
    'activation_authority': 'NONE',
    'exact_scm_qualification': 'REQUIRED_SEPARATELY_IN_013B_AFTER_ACCEPTED_INTEGRATION',
}


@dataclass(frozen=True)
class ScienceCommitOwnerEvidence:
    """Actual root and policy binding, not a fabricated Writer PID or clock."""
    root_identity: str
    topology_fingerprint: str
    topology_version: int
    lease_identity: str
    lease_name: str
    owner_sid: str
    descriptor_sha256: str
    storage_profile: str = 'SCIENCE_NONOWNER_COMMIT_STORAGE_007_V1'
    profile: str = 'EXISTING_WRITER_ACCOUNT_DOMAIN_CUSTODY_007_V1'


class ScienceCustodyStorageSet:
    """One explicitly supplied, lifetime-locked Science mailbox and its views.

The native backend binds every root, SID and descriptor before this object is
constructed. No paths, account identity or permissions come from requests.
This class never constructs a Writer backend, changes ACLs or activates it.
The caller owns this object's lifetime independently of recorder views.
"""
    def __init__(self, client: ScienceCustodyMailboxClient, *,
                 timeout_seconds: float = 10.0, poll_seconds: float = 0.1,
                 recovery_clock=None, readiness_trace=None):
        if not isinstance(client, ScienceCustodyMailboxClient):
            raise CustodyCommitError('An explicit Science mailbox client is required.')
        if (isinstance(timeout_seconds, bool) or isinstance(poll_seconds, bool)
                or not 0 < poll_seconds <= timeout_seconds <= 60):
            raise CustodyCommitError('Finite positive commit wait bounds are required.')
        self.client = client
        self.backend = client.mailbox_backend
        if self.backend.role != 'science':
            raise CustodyCommitError('Science cannot use the trusted Writer backend.')
        self.timeout_seconds = float(timeout_seconds)
        self.poll_seconds = float(poll_seconds)
        self._lock = threading.RLock()
        self._readiness_trace = readiness_trace
        self._closed = False
        self._pending = self._result = None
        self._reconfirming = False
        self.roots = self.backend.validate_readonly_roots()
        self.source_root_identity = self.backend.source_root_identity
        self.derived_root = self.backend.derived_root
        self.policy_version = getattr(getattr(self.backend, 'policy', None), 'version', 1)
        self.reader_lock_opener = self.backend.open_reader_lock if self.policy_version == 2 else None
        # Before any new namespace guards are opened, reconcile an old transport
        # receipt. The subsequent canonical startup audit still has to succeed.
        pending = self.client.recover_pending()
        if pending is not None:
            result = self._await(pending)
            self.client.acknowledge(pending, result)
        orphans = self.client.orphaned_staging()
        if orphans:
            if not callable(recovery_clock):
                raise CustodyCommitPending('Orphan cleanup requires an explicit current observation clock.')
            for orphan in orphans:
                pending = self.client.submit_orphan_receipt(orphan, observed_at=recovery_clock())
                result = self._await(pending)
                self.client.acknowledge(pending, result)

    def _ensure_open(self):
        if self._closed:
            raise CustodyCommitError('Science custody channel is closed.')

    @contextmanager
    def _stage(self, name, alias=None, relative=None):
        detail = {} if alias is None else {'alias': alias, 'relative_path': str(relative)}
        try:
            if self._readiness_trace is not None:
                self._readiness_trace(name + '_ENTER', **detail)
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                if self._readiness_trace is not None:
                    self._readiness_trace(name + '_EXIT', **detail)
            except Exception:
                pass

    def _await(self, pending):
        with self._stage('SCIENCE_CUSTODY_AWAIT'):
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                result = self.client.reconcile(pending)
                if result is not None:
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CustodyCommitPending('Commit outcome pending; staging and request preserved.')
                time.sleep(min(self.poll_seconds, remaining))

    def root(self, alias):
        if alias not in ('arrivals', 'custody', 'cursors'):
            raise CustodyCommitError('Unknown authoritative root alias.')
        return self.backend.namespace_root(alias)

    def storage(self, alias, *, expected_root: Path, source_root_identity: str):
        self._ensure_open()
        if (source_root_identity != self.source_root_identity
                or Path(expected_root).resolve(strict=True) != self.root(alias)):
            raise CustodyCommitError('Recorder root/source identity differs from sealed policy.')
        return SealedScienceStorage(self, alias)

    def publish(self, alias, relative, raw, *, crash_after_temp=False):
        self._ensure_open()
        with self._stage('SCIENCE_CUSTODY_PUBLISH', alias, relative):
            with self._lock:
                if self._pending is not None:
                    raise CustodyCommitPending('Prior publication must be locally verified before another commit.')
                pending = self.client.submit(final_root=alias, relative_path=PurePath(relative).as_posix(),
                                             raw=bytes(raw), crash_after_stage=crash_after_temp)
                self._pending = pending
                self._result = self._await(pending)
                return self._result.created

    def publication_verified(self, alias, relative, raw):
        self._ensure_open()
        with self._stage('SCIENCE_CUSTODY_ACK', alias, relative):
            with self._lock:
                if self._pending is None or self._result is None:
                    raise CustodyCommitError('No pending committed publication to acknowledge.')
                request = self._pending.request
                if (request.final_root != alias
                        or request.final_relative_path != PurePath(relative).as_posix()
                        or request.content_sha256 != hashlib.sha256(raw).hexdigest()
                        or request.byte_length != len(raw)):
                    raise CustodyCommitError('Local publication acknowledgement differs from pending identity.')
                # Reconcile performs a fresh trusted receipt/final readback. The
                # caller's notification success cannot replace that authority.
                result = self.client.reconcile(self._pending)
                if result is None or result.receipt != self._result.receipt:
                    raise CustodyCommitError('Receipt changed before local acknowledgement.')
                self.client.acknowledge(self._pending, result)
                self._pending = self._result = None

    def read_committed(self, alias, relative):
        self._ensure_open()
        relative = PurePath(relative).as_posix()
        with self._lock:
            try:
                with self._stage('SCIENCE_CUSTODY_READ_CONFIRM', alias, relative):
                    evidence = self.client.read_confirmed(alias, relative)
            except CustodyCommitPending:
                with self._stage('SCIENCE_CUSTODY_INSPECT_EXISTING', alias, relative):
                    inspected = self.client.inspect_existing(alias, relative)
                if inspected is None:
                    raise WriterPhysicalStorageError('Unconfirmed object disappeared.')
                original, visible = inspected
                if self._pending is None:
                    # Same logical commit, new bounded transport generation.
                    # No scientific record is minted and no raw is adopted.
                    self._pending = self.client.submit(final_root=alias, relative_path=relative,
                                                       raw=visible.raw)
                    self._reconfirming = True
                elif self._pending.request.commit_binding() != original.commit_binding():
                    raise CustodyCommitPending('Another publication remains pending; reconfirmation deferred.')
                self._result = self._await(self._pending)
                with self._stage('SCIENCE_CUSTODY_READ_CONFIRM', alias, relative):
                    evidence = self.client.read_confirmed(alias, relative)
            if evidence is None:
                raise WriterPhysicalStorageError('Committed object is absent.')
            if (self._reconfirming and self._pending.request.final_root == alias
                    and self._pending.request.final_relative_path == relative):
                # Only recovery of existing raw may retire its transport here.
                # New publication retains the owner's registration callback.
                result = self.client.reconcile(self._pending)
                if result is None:
                    raise CustodyCommitPending('Reconfirmation disappeared before cleanup.')
                self.client.acknowledge(self._pending, result)
                self._pending = self._result = None
                self._reconfirming = False
            return evidence.raw

    def close(self):
        if not self._closed:
            self._closed = True
            self.backend.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class SealedScienceStorage:
    """Reader-only physical view with Writer-mediated singleton publication."""
    def __init__(self, storage_set, alias):
        self.storage_set = storage_set
        self.alias = alias
        self.root = storage_set.root(alias)
        self._closed = False
        evidence = storage_set.roots[alias]
        root_identity = ':'.join(map(str, evidence.file_identity))
        self.owner_evidence = ScienceCommitOwnerEvidence(
            root_identity=root_identity,
            topology_fingerprint=storage_set.backend.policy_sha256,
            topology_version=storage_set.policy_version,
            lease_identity=hashlib.sha256((storage_set.backend.policy_sha256 + ':' +
                                          alias + ':' + root_identity).encode('ascii')).hexdigest(),
            lease_name='SCIENCE_TRANSPORT_LIFETIME_LOCK_NOT_WRITER_PROCESS_IDENTITY',
            owner_sid=evidence.owner_sid, descriptor_sha256=evidence.descriptor_sha256)

    @contextmanager
    def transaction(self):
        if self._closed:
            raise WriterPhysicalStorageError('Sealed Science view is closed.')
        self.storage_set._ensure_open()
        with self.storage_set._lock:
            yield

    def atomic_create(self, relative_path, data, *, crash_after_temp=False):
        with self.transaction():
            return self.storage_set.publish(self.alias, relative_path, data,
                                            crash_after_temp=crash_after_temp)

    def publication_verified(self, relative_path, raw):
        self.storage_set.publication_verified(self.alias, relative_path, raw)

    def read_committed(self, relative_path):
        with self.transaction():
            return self.storage_set.read_committed(self.alias, relative_path)

    def iter_files(self, relative_directory, *, suffix):
        with self.transaction():
            return self.storage_set.backend.iter_trusted(
                self.alias, PurePath(relative_directory).as_posix(), suffix=suffix)

    def quarantine_partials(self):
        # Transport staging lives outside raw. Legacy in-place partials cannot
        # silently acquire authority or be moved by the sealed Science reader.
        if self.iter_files(PurePath('.partial'), suffix=''):
            raise WriterPhysicalStorageError('Legacy raw partials require separately proven migration.')

    def close(self):
        self._closed = True
