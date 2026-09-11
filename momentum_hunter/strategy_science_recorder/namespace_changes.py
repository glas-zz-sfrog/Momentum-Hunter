"""Caller-driven local Windows namespace change hints, never evidence authority.

Register before the owner's baseline inventory. New/touched names are validated
by that owner. Content coherence is a separate R-lease responsibility. Overflow,
unsupported roots and malformed notifications require explicit recovery; they
are never an empty-success notification or a silently repeated full scan.
"""
from __future__ import annotations
import ctypes as ct
from ctypes import wintypes as wt
from pathlib import Path
import struct

from .verified_reads import (
    VerifiedReadError, _Overlapped, _directory_identity,
    _kernel, _unretired_requests,
)


class NamespaceRecoveryRequired(VerifiedReadError):
    """No complete incremental namespace view can currently be established."""


class DirectoryChanges:
    """One serialized foreground consumer; no thread or scheduler activation."""

    def __init__(self, root: Path, *, recursive: bool = False, buffer_bytes: int = 65536):
        if buffer_bytes < 1024 or buffer_bytes > 65536 or buffer_bytes % 4:
            raise ValueError('Notification buffer must be aligned and between 1KiB and 64KiB.')
        self.root = Path(root).absolute()
        if str(self.root).startswith('\\\\') or self.root.resolve(strict=True) != self.root:
            raise NamespaceRecoveryRequired('Namespace hints require an exact local root.')
        self.identity = _directory_identity(self.root)
        self.kernel = _kernel()
        self.kernel.ReadDirectoryChangesW.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD, wt.BOOL, wt.DWORD, ct.POINTER(wt.DWORD), ct.POINTER(_Overlapped), ct.c_void_p]
        self.kernel.ReadDirectoryChangesW.restype = wt.BOOL
        self.kernel.GetFinalPathNameByHandleW.argtypes = [wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD]
        self.kernel.GetFinalPathNameByHandleW.restype = wt.DWORD
        self.handle = self.event = None
        self.pending = False
        self.closed = self.failed = False
        self.recursive = recursive
        self.buffer = (wt.DWORD * (buffer_bytes // 4))()
        self.overlapped = _Overlapped()
        self.counters = {'drains': 0, 'notifications': 0, 'batches': 0}
        try:
            # FILE_LIST_DIRECTORY; sharing read/write but not directory deletion.
            self.handle = self.kernel.CreateFileW(str(self.root), 1, 3, None, 3, 0x42200000, None)
            if self.handle == wt.HANDLE(-1).value:
                self.handle = None
                raise NamespaceRecoveryRequired('Cannot pin namespace notification root.')
            final_path = ct.create_unicode_buffer(32768)
            length = self.kernel.GetFinalPathNameByHandleW(self.handle, final_path, len(final_path), 0)
            text = final_path.value
            if text.startswith('\\\\?\\'):
                text = text[4:]
            # Python stat's volume identity need not use the Win32 legacy
            # 32-bit volume-serial representation. Compare like APIs, and bind
            # the opened non-delete-shared root to its final canonical path.
            if not length or length >= len(final_path) or Path(text) != self.root or _directory_identity(self.root) != self.identity:
                raise NamespaceRecoveryRequired('Opened notification root differs from requested identity.')
            self.event = self.kernel.CreateEventW(None, True, False, None)
            if not self.event:
                raise NamespaceRecoveryRequired('Cannot allocate namespace event.')
            self._arm()
        except BaseException:
            self.close()
            raise

    def _arm(self):
        self.overlapped = _Overlapped()
        self.overlapped.hEvent = self.event
        if not self.kernel.ReadDirectoryChangesW(self.handle, self.buffer, ct.sizeof(self.buffer), self.recursive, 3, None, ct.byref(self.overlapped), None):
            self.failed = True
            raise NamespaceRecoveryRequired('Namespace notification registration failed.')
        self.pending = True

    @staticmethod
    def _decode(raw: bytes) -> tuple[str, ...]:
        names = []
        offset = 0
        while True:
            if offset + 12 > len(raw):
                raise NamespaceRecoveryRequired('Truncated namespace notification header.')
            next_offset, action, byte_length = struct.unpack_from('<III', raw, offset)
            end = offset + 12 + byte_length
            if action not in {1, 2, 3, 4, 5} or not byte_length or byte_length % 2 or end > len(raw):
                raise NamespaceRecoveryRequired('Invalid namespace notification identity or length.')
            try:
                name = raw[offset + 12:end].decode('utf-16-le', errors='strict')
            except UnicodeError as exc:
                raise NamespaceRecoveryRequired('Invalid namespace notification encoding.') from exc
            parts = name.replace('\\', '/').split('/')
            if any(part in {'', '.', '..'} or ':' in part or '\x00' in part for part in parts):
                raise NamespaceRecoveryRequired('Namespace notification escapes its root.')
            names.append('/'.join(parts))
            if not next_offset:
                if len(raw) - end > 3:
                    raise NamespaceRecoveryRequired('Unexpected trailing namespace notification bytes.')
                break
            if next_offset % 4 or next_offset < 12 + byte_length or offset + next_offset >= len(raw):
                raise NamespaceRecoveryRequired('Invalid namespace notification chain.')
            offset += next_offset
        return tuple(names)

    def drain(self) -> tuple[str, ...]:
        if self.closed or self.failed:
            raise NamespaceRecoveryRequired('Namespace generation is closed or failed.')
        if _directory_identity(self.root) != self.identity:
            self.failed = True
            raise NamespaceRecoveryRequired('Namespace root identity changed.')
        self.counters['drains'] += 1
        names = {}
        # A storm cannot monopolize admission indefinitely. This is a work bound,
        # not a performance acceptance gate: excess is explicit recovery-needed.
        for _ in range(256):
            count = wt.DWORD()
            complete = self.kernel.GetOverlappedResult(self.handle, ct.byref(self.overlapped), ct.byref(count), False)
            error = ct.get_last_error()
            if not complete:
                if error == 996:  # ERROR_IO_INCOMPLETE, request remains pending.
                    return tuple(names)
                self.failed = True
                raise NamespaceRecoveryRequired('Namespace notification error; recovery required.')
            self.pending = False
            if not count.value or count.value > ct.sizeof(self.buffer):
                self.failed = True
                raise NamespaceRecoveryRequired('Namespace notification overflow; recovery required.')
            raw = ct.string_at(ct.addressof(self.buffer), count.value)
            # Completed data is copied before rearming the same handle. Windows
            # retains changes between requests in the handle's notification queue.
            self._arm()
            try:
                decoded = self._decode(raw)
            except BaseException:
                self.failed = True
                raise
            self.counters['batches'] += 1
            self.counters['notifications'] += len(decoded)
            names.update((name, None) for name in decoded)
        self.failed = True
        raise NamespaceRecoveryRequired('Namespace change storm requires explicit recovery.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.handle and self.pending:
            self.kernel.CancelIoEx(self.handle, ct.byref(self.overlapped))
            waited = self.kernel.WaitForSingleObject(self.event, 5000)
            count = wt.DWORD()
            complete = self.kernel.GetOverlappedResult(self.handle, ct.byref(self.overlapped), ct.byref(count), False)
            if waited != 0 or (not complete and ct.get_last_error() == 996):
                _unretired_requests.append(self)
                self.kernel.CloseHandle(self.handle)
                self.handle = None
                raise NamespaceRecoveryRequired('Namespace cancellation retirement is unproven.')
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.event:
            self.kernel.CloseHandle(self.event)
            self.event = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
