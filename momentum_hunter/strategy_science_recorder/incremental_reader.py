"""Explicit Science004 incremental use of the unchanged canonical V2 ingress."""
from pathlib import Path
from ..strategy_science_source_reader import (
    StrategyScienceSourceReaderV2, ReaderCursorState, SourceReaderCursorError,
    CURSOR_FILE,
)
from .canonical import canonical_json_v1, sha256_hex, strict_json_loads
from .verified_reads import VerifiedReads, VerifiedReadError
from .namespace_changes import DirectoryChanges
from .incremental_state import StreamHeads


class IncrementalScienceReader(StrategyScienceSourceReaderV2):
    """No default Reader behavior change; fast mode belongs to one owner scope."""
    def __init__(self, *args, publication_index, **kwargs):
        self.publication_index = publication_index
        self._view = None
        self._cursor_reads = self._cursor_changes = None
        self._cursor_paths = set()
        self.last_delta = ()
        try:
            super().__init__(*args, **kwargs)
        except BaseException:
            self._close_guards()
            raise

    @property
    def _fast(self):
        return self.recorder._views is not None and self.recorder._views.incremental

    def _inventory(self):
        if getattr(self, 'recorder', None) is not None and self._fast:
            return self.publication_index()
        return super()._inventory()

    def _check_cursor(self):
        self._cursor_reads.check_content()
        for name in self._cursor_changes.drain():
            if Path(name).parts[0] == '.partial':
                continue
            path = self.cursor_root / name
            if path not in self._cursor_paths:
                raise SourceReaderCursorError('Cursor namespace is ahead of locally verified commits.')
            raw = self._cursor_reads.read(path)
            match = CURSOR_FILE.fullmatch(path.name)
            if match is None or sha256_hex(raw) != match.group('sha256'):
                raise SourceReaderCursorError('Changed cursor does not bind exact committed bytes.')
        self._cursor_reads.check_content()

    def _load_state(self):
        if self._fast and self._view is not None:
            self._ensure_open()
            self._check_cursor()
            return self._view
        if self._cursor_reads is None:
            self._cursor_changes = DirectoryChanges(self.cursor_root, recursive=True)
            self._cursor_reads = VerifiedReads(self.cursor_root, aggregate_content=True)
        value = super()._load_state()
        heads = StreamHeads()
        for stream, head in value.stream_heads.items():
            heads = heads.set(stream, head)
        for path, _cursor, raw in super()._cursor_entries():
            if self._cursor_reads.read(path) != raw:
                raise SourceReaderCursorError('Cursor changed during startup audit.')
            self._cursor_paths.add(path)
        self._check_cursor()
        self._view = ReaderCursorState(value.final_disposition, value.last_publication_ordinal, value.last_reader_cursor_sha256, value.session_id, heads, value.terminal)
        return self._view

    def _verify_custody_commit(self, envelope, custody):
        if not self._fast:
            return super()._verify_custody_commit(envelope, custody)
        self.last_delta = self.recorder.verify_commit_delta(envelope, custody)

    def _cursor_committed(self, path, raw, envelope, custody, previous):
        if not self._fast:
            return
        if self._cursor_reads.read(path) != raw:
            raise SourceReaderCursorError('Installed cursor differs from exact requested bytes.')
        value = strict_json_loads(raw)
        self._validate_cursor_value(value)
        if canonical_json_v1(value) != raw:
            raise SourceReaderCursorError('Installed cursor is not canonical.')
        required = {
            'custody_checkpoint_sha256': custody.checkpoint_sha256,
            'custody_status': custody.status,
            'publication_ordinal': previous.last_publication_ordinal + 1,
            'previous_reader_cursor_sha256': previous.last_reader_cursor_sha256,
            'previous_source_envelope_sha256': envelope.previous_record_sha256,
            'source_envelope_sha256': envelope.raw_sha256,
            'source_event_id': envelope.source_event_id,
            'source_stream_id': envelope.stream_id,
            'source_sequence': envelope.source_sequence,
            'source_effective_known_at': envelope.effective_known_at,
            'source_emitted_at': envelope.emitted_at,
            'session_id': envelope.session_id,
            'source_owner_identity': envelope.source_owner_identity,
            'source_interface_identity': envelope.source_interface_identity,
            'manifest_phase': self._manifest_phase(envelope),
            'final_disposition': self._final_disposition(envelope),
            'terminal': self._manifest_phase(envelope) == 'FINAL',
        }
        if any(value.get(field) != expected for field, expected in required.items()):
            raise SourceReaderCursorError('New cursor source/custody/previous-head binding is false.')
        public_path = self._inventory().get(required['publication_ordinal'])
        if public_path is None or value['publication_file'] != public_path.name or value['source_publication_identity_sha256'] != self._publication_identity(public_path.name, required['publication_ordinal'], envelope.raw_sha256):
            raise SourceReaderCursorError('New cursor publication identity is false.')
        match = CURSOR_FILE.fullmatch(path.name)
        if match is None or int(match.group('ordinal')) != required['publication_ordinal'] or match.group('sha256') != sha256_hex(raw):
            raise SourceReaderCursorError('New cursor path identity is false.')
        self._cursor_paths.add(path)
        self._check_cursor()
        self._view = ReaderCursorState(required['final_disposition'], required['publication_ordinal'], sha256_hex(raw), envelope.session_id, previous.stream_heads.set(envelope.stream_id, (envelope.source_sequence, envelope.raw_sha256)), required['terminal'])

    def _close_guards(self):
        try:
            if self._cursor_changes is not None:
                self._cursor_changes.close()
        finally:
            if self._cursor_reads is not None:
                self._cursor_reads.close()

    def close(self):
        try:
            super().close()
        finally:
            self._close_guards()
